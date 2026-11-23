#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨目录派发 Claude Code 后台会话。

问题背景
--------
`claude --bg` 的 worker 由常驻 daemon 拉起。daemon 在**首次启动时**继承启动它的
那个进程的环境变量，之后所有 worker 复用同一份。如果 daemon 是从一个把
`ANTHROPIC_BASE_URL` 指向本地转发代理的 shell 里启动的，那么：

  1. 该代理端口随原进程退出而失效；
  2. daemon 仍然把这个已死地址传给每一个新 worker；
  3. worker 表现为 `Connection refused (ECONNREFUSED)` 无限重试，零输出。

这不是某个客户端或某个代理的特例。任何"本地中转代理 + daemon 复用"的组合都会
中招。因此派发时必须显式给出长期有效的 provider 配置，而不是继承。

第二个风险是续跑跑错仓：把 A 仓的会话在 B 仓目录 resume，CLI 不报错，会话会
静默在 B 仓里运行——它以为自己还在 A 仓。本工具在续跑前核验 session 归属。

配置
----
所有环境相关值从配置文件读，代码里不写死任何地址。查找顺序：

  1. `$CC_DISPATCH_CONFIG`
  2. `<repo>/tools/cc-dispatch/config.json`（本机，已 gitignore）
  3. `~/.claude/dispatch/config.json`

最小配置：

  {"providers": {"default": {
      "base_url": "https://<your-gateway>/api",
      "auth_token": "<token>",
      "model": "<model-id>"
  }}}

auth_token 也可以用 `auth_token_env` 指定从环境变量读，避免明文落盘。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# 必须剥掉的环境变量。
#
# 前 8 个：daemon 会把它们传染给 worker，指向可能已失效的本地代理。
# 后 3 个：会把 worker 挂到父会话的 messaging socket 上，导致跨会话消息串流。
STRIP_ENV = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_LAUNCHED_BY_SESSION_IDS",
)

# 后台会话没有终端，遇到权限确认弹窗会永久 waiting。
# 默认用 dontAsk：不需要授权的动作照常做，需要授权的直接拒绝而不是卡住。
# 需要更强的自主性时用 --permission-mode bypassPermissions 显式选择。
DEFAULT_PERMISSION_MODE = "dontAsk"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_CONFIG = os.path.join(REPO_ROOT, "tools", "cc-dispatch", "config.json")
USER_CONFIG = os.path.join(os.path.expanduser("~"), ".claude", "dispatch", "config.json")


class DispatchError(Exception):
    """可直接展示给用户的失败，不含凭据。"""


# ------------------------------------------------------------------ 配置

def config_paths() -> list:
    """按优先级列出候选配置文件路径。"""
    paths = []
    env_path = os.environ.get("CC_DISPATCH_CONFIG")
    if env_path:
        paths.append(env_path)
    paths.extend([LOCAL_CONFIG, USER_CONFIG])
    return paths


def load_config(path: str | None = None) -> dict:
    """读配置。显式给 path 时只读那一个，便于测试。"""
    if path:
        return _read_config_file(path)
    for candidate in config_paths():
        if os.path.isfile(candidate):
            return _read_config_file(candidate)
    raise DispatchError(
        "找不到配置文件。请创建以下任一路径：\n  "
        + "\n  ".join(config_paths())
        + "\n格式见 tools/cc-dispatch/README.md"
    )


def _read_config_file(path: str) -> dict:
    try:
        with open(path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise DispatchError(f"配置文件不存在：{path}")
    except json.JSONDecodeError as exc:
        raise DispatchError(f"配置文件不是合法 JSON：{path}（{exc.msg}）")
    if not isinstance(cfg, dict):
        raise DispatchError(f"配置文件顶层必须是对象：{path}")
    return cfg


def resolve_provider(config: dict, name: str = "default") -> dict:
    """取一个 provider 的三元组，并把 auth_token_env 解析成实际值。"""
    providers = config.get("providers") or {}
    if name not in providers:
        known = ", ".join(sorted(providers)) or "(空)"
        raise DispatchError(f"配置里没有 provider {name!r}；可用：{known}")
    p = dict(providers[name])

    base = (p.get("base_url") or "").strip()
    if not base:
        raise DispatchError(f"provider {name!r} 缺少 base_url")
    if _is_loopback(base):
        raise DispatchError(
            f"provider {name!r} 的 base_url 指向本机端口（{base}）。\n"
            "本机转发代理的端口随其宿主进程退出而失效，不能用于后台会话。\n"
            "请改成长期可达的网关地址。"
        )

    token = (p.get("auth_token") or "").strip()
    if not token:
        env_name = (p.get("auth_token_env") or "").strip()
        if not env_name:
            raise DispatchError(
                f"provider {name!r} 需要 auth_token 或 auth_token_env"
            )
        token = (os.environ.get(env_name) or "").strip()
        if not token:
            raise DispatchError(
                f"provider {name!r} 的 auth_token_env={env_name}，"
                "但该环境变量为空或未设置"
            )

    model = (p.get("model") or "").strip()
    return {"base_url": base, "auth_token": token, "model": model}


_LOOPBACK_HOSTS = (
    "127.0.0.1", "localhost", "0.0.0.0", "[::1]", "::1",
    "host.docker.internal", "host.containers.internal",
)


def _is_loopback(url: str) -> bool:
    """判断地址是否只在本机可达。

    这类地址活不过宿主进程，不能用于后台会话。兼容有 scheme、无 scheme、
    带端口和不带端口几种写法，避免文档承诺强于实现。
    """
    lowered = url.strip().lower()
    for prefix in ("http://", "https://"):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):]
            break
    # 去掉路径，只留 host[:port]
    host = lowered.split("/", 1)[0]
    # IPv6 带方括号时保留括号
    if host.startswith("["):
        host = host.split("]", 1)[0] + "]"
    else:
        host = host.rsplit(":", 1)[0] if ":" in host else host
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def redact(text: str, secrets) -> str:
    """把已知敏感值从文本里抹掉。"""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


# ------------------------------------------------------------------ 会话归属

def claude_home() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude")


def projects_root() -> str:
    return os.path.join(claude_home(), "projects")


def session_cwd(session_id: str, projects_root: str | None = None) -> str | None:
    """查一个 session 属于哪个工作目录。

    transcript 位于 `~/.claude/projects/<slug>/<session-id>.jsonl`，slug 是绝对
    路径把 / 换成 -。优先读 transcript 里的 cwd 字段，比反解 slug 可靠。
    """
    root = projects_root or globals()["projects_root"]()
    if not os.path.isdir(root):
        return None
    for slug in os.listdir(root):
        path = os.path.join(root, slug, f"{session_id}.jsonl")
        if not os.path.isfile(path):
            continue
        cwd = _read_cwd_field(path)
        if cwd:
            return cwd
        if slug.startswith("-"):
            return slug.replace("-", "/")
    return None


def _read_cwd_field(path: str) -> str | None:
    try:
        with open(path) as f:
            for _ in range(50):
                line = f.readline()
                if not line:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and rec.get("cwd"):
                    return rec["cwd"]
    except OSError:
        return None
    return None


def _norm(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path)).rstrip("/")


def assert_resume_dir(session_id: str, target_dir: str,
                      projects_root: str | None = None) -> None:
    """续跑前确认 session 原本就在这个目录，否则拒绝。

    没有这道校验，把 A 仓的会话在 B 仓 resume 会静默在 B 仓执行——CLI 不报错，
    而会话的上下文仍然属于 A 仓。
    """
    owner = session_cwd(session_id, projects_root)
    if owner is None:
        raise DispatchError(
            f"找不到 session {session_id} 的 transcript，无法确认归属目录。\n"
            "编辑器内嵌 agent（非终端入口）的会话不在 CLI 的会话体系里，"
            "不能用 resume 续跑。"
        )
    if _norm(owner) != _norm(target_dir):
        raise DispatchError(
            f"session {session_id} 属于 {owner}，不能在 {_norm(target_dir)} 里续跑。\n"
            "换目录续跑会让它以为自己在原仓、实际改的是这里的文件。"
        )


# ------------------------------------------------------------------ 参数校验

def validate_start_args(directory: str, name: str, prompt: str) -> None:
    if not directory:
        raise DispatchError("缺少目录参数")
    if not os.path.isdir(os.path.expanduser(directory)):
        raise DispatchError(f"目录不存在：{directory}")
    if not name:
        raise DispatchError("缺少会话名（用于跨会话寻址）")
    if any(c in name for c in "/ \t"):
        raise DispatchError(f"会话名不能含斜杠或空白：{name!r}")
    if not prompt.strip():
        raise DispatchError("缺少任务内容")


# ------------------------------------------------------------------ 环境与命令

def clean_env(env: dict) -> dict:
    return {k: v for k, v in env.items() if k not in STRIP_ENV}


def is_wrapper_path(path: str) -> bool:
    """识别常见的包装脚本名，避免把包装器当成真二进制。"""
    base = os.path.basename(path)
    return "wrapper" in base or base.endswith("-acp")


def resolve_binary() -> str:
    """优先用版本目录下的真二进制，绕开 PATH 上可能的包装脚本。"""
    versions_dir = os.path.join(os.path.expanduser("~"), ".local", "share",
                                "claude", "versions")
    if os.path.isdir(versions_dir):
        for v in sorted(os.listdir(versions_dir), reverse=True):
            p = os.path.join(versions_dir, v)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    import shutil
    found = shutil.which("claude")
    if found and not is_wrapper_path(found):
        return found
    raise DispatchError("找不到可用的 claude 二进制")


def build_start_argv(directory: str, name: str, prompt: str,
                     binary: str | None = None,
                     permission_mode: str | None = None) -> list:
    mode = permission_mode or DEFAULT_PERMISSION_MODE
    return [binary or resolve_binary(), "--bg",
            "--permission-mode", mode, "-n", name, prompt]


def build_resume_argv(session_id: str, prompt: str,
                      binary: str | None = None,
                      permission_mode: str | None = None) -> list:
    mode = permission_mode or DEFAULT_PERMISSION_MODE
    return [binary or resolve_binary(), "--resume", session_id, "-p",
            "--permission-mode", mode, prompt]


def _agents_json() -> list:
    import shutil
    exe = shutil.which("claude")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "agents", "--json"], text=True,
                             capture_output=True, timeout=15).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return []


def is_session_running(session_id: str) -> bool:
    """运行中的后台会话不能被 resume；先给出可操作提示。"""
    short = session_id[:8]
    for r in _agents_json():
        if r.get("id") == short or r.get("sessionId") == session_id:
            return (r.get("state") or r.get("status")) in ("working", "busy")
    return False


# ------------------------------------------------------------------ 执行

def _run(argv: list, cwd: str, provider: dict) -> int:
    env = clean_env(dict(os.environ))
    env["ANTHROPIC_BASE_URL"] = provider["base_url"]
    env["ANTHROPIC_AUTH_TOKEN"] = provider["auth_token"]
    if provider.get("model"):
        env["ANTHROPIC_MODEL"] = provider["model"]
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, text=True,
                              capture_output=True)
    except FileNotFoundError:
        raise DispatchError(f"无法执行：{argv[0]}")
    secrets = [provider["auth_token"]]
    if proc.stdout.strip():
        print(redact(proc.stdout.strip(), secrets))
    if proc.returncode != 0:
        err = redact((proc.stderr or "").strip(), secrets)
        if err:
            print(err, file=sys.stderr)
    return proc.returncode


def cmd_start(args) -> int:
    validate_start_args(args.directory, args.name, args.prompt)
    provider = resolve_provider(load_config(), args.provider)
    argv = build_start_argv(args.directory, args.name, args.prompt,
                            permission_mode=getattr(args, "permission_mode", None))
    return _run(argv, os.path.expanduser(args.directory), provider)


def cmd_resume(args) -> int:
    if not args.session_id:
        raise DispatchError("缺少 session id")
    if not args.prompt.strip():
        raise DispatchError("缺少任务内容")
    if not os.path.isdir(os.path.expanduser(args.directory)):
        raise DispatchError(f"目录不存在：{args.directory}")
    assert_resume_dir(args.session_id, args.directory)
    if is_session_running(args.session_id):
        raise DispatchError(
            f"session {args.session_id[:8]} 还在后台运行，不能直接 resume。\n"
            f"先 `claude stop {args.session_id[:8]}`，或 `claude attach "
            f"{args.session_id[:8]}` 进入它的终端继续对话。"
        )
    provider = resolve_provider(load_config(), args.provider)
    argv = build_resume_argv(args.session_id, args.prompt,
                             permission_mode=getattr(args, "permission_mode", None))
    return _run(argv, os.path.expanduser(args.directory), provider)


def cmd_list(args) -> int:
    rows = _agents_json()
    bg = [r for r in rows if r.get("kind") == "background"]
    if not bg:
        print("没有后台会话。")
        return 0
    for r in bg:
        state = r.get("state") or r.get("status") or "?"
        print(f"{r.get('id'):9} {state:9} {r.get('name') or '-':24} {r.get('cwd')}")
    return 0


def cmd_check(args) -> int:
    """检查配置是否可用，不启动任何会话。"""
    cfg = load_config()
    name = args.provider
    provider = resolve_provider(cfg, name)
    print(f"provider   : {name}")
    print(f"base_url   : {provider['base_url']}")
    print(f"model      : {provider['model'] or '(继承默认)'}")
    print(f"auth_token : {'已配置（%d 字符）' % len(provider['auth_token'])}")
    print(f"binary     : {resolve_binary()}")
    return 0


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="cc-dispatch",
        description="跨目录派发 Claude Code 后台会话")
    p.add_argument("--provider", default="default",
                   help="使用配置里的哪个 provider（默认 default）")
    p.add_argument("--permission-mode", default=DEFAULT_PERMISSION_MODE,
                   choices=["dontAsk", "acceptEdits", "bypassPermissions", "plan"],
                   help="后台会话的权限模式（默认 dontAsk：需要授权的动作直接拒绝，"
                        "不会因无终端确认而卡死）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="新建后台会话并立刻开始")
    s.add_argument("directory")
    s.add_argument("name")
    s.add_argument("prompt")
    s.set_defaults(func=cmd_start)

    r = sub.add_parser("resume", help="续跑已有会话（多轮）")
    r.add_argument("session_id")
    r.add_argument("directory")
    r.add_argument("prompt")
    r.set_defaults(func=cmd_resume)

    ls = sub.add_parser("list", help="列出后台会话")
    ls.set_defaults(func=cmd_list)

    ck = sub.add_parser("check", help="检查配置是否可用")
    ck.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except DispatchError as exc:
        print(f"cc-dispatch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
