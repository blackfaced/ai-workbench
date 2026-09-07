#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""问客户端自己：你现在到底能发现哪些 Skill。

Codex 与 Trae CLI 都带 `app-server`（stdio JSON-RPC），其中的 `skills/list`
返回的是客户端真正加载的集合 —— 它会把 ~/.agents/skills 和自家目录合到一起。
按单个目录各扫各的判断不出重名，所以检查器优先走这里。
纯本地调用，不发模型请求。

    用法：python3 skills_discovery.py <codex|traecli>
    输出：每行 "<name>\t<SKILL.md 绝对路径>"，退出码 0 表示这份清单可信

退出码：2 用法错 / 3 起不来 / 4 超时 / 5 JSON-RPC error / 6 清单本身带解析错误。
非 0 一律表示「这份清单不可信」，调用方必须当成检查失败，不能当成空清单放过。
"""

import json
import os
import select
import subprocess
import sys
import time

TIMEOUT_SEC = float(os.environ.get("AIWB_DISCOVERY_TIMEOUT", "45"))


def read_answer(proc, want_id, deadline):
    """在 deadline 之前等一条 id=want_id 的响应。

    不用 readline()：它是阻塞的，外层的 deadline 对它没有任何约束力 ——
    服务端一直不换行就一直挂着。这里按 fd 可读性推进，超时是真的超时。
    """
    fd = proc.stdout.fileno()
    buffered = b""
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return None
        ready, _, _ = select.select([fd], [], [], min(remaining, 0.5))
        if not ready:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            return None  # 对端关了管道
        buffered += chunk
        while b"\n" in buffered:
            raw, buffered = buffered.split(b"\n", 1)
            try:
                message = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if message.get("id") == want_id:
                return message


def reap(proc):
    """收干净子进程：管道全关、先 terminate 再 kill，最后 wait 掉僵尸。"""
    for stream in (proc.stdin, proc.stdout):
        try:
            if stream:
                stream.close()
        except (IOError, OSError):
            pass
    if proc.poll() is None:
        proc.terminate()
        deadline = time.time() + 2
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
    proc.wait()


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("用法：skills_discovery.py <codex|traecli>\n")
        return 2
    binary = argv[0]
    try:
        proc = subprocess.Popen([binary, "app-server"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except OSError as exc:
        sys.stderr.write("起不来 %s app-server：%s\n" % (binary, exc))
        return 3

    deadline = time.time() + TIMEOUT_SEC
    answer = None
    try:
        for payload in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"clientInfo": {"name": "ai-workbench-env",
                                       "title": "ai-workbench-env",
                                       "version": "1.0.0"}}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "skills/list", "params": {}},
        ):
            proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        proc.stdin.flush()
        answer = read_answer(proc, 2, deadline)
    except (IOError, OSError) as exc:
        sys.stderr.write("与 %s app-server 通信失败：%s\n" % (binary, exc))
        return 3
    finally:
        reap(proc)

    if answer is None:
        sys.stderr.write("%s app-server 没在 %gs 内回 skills/list\n" % (binary, TIMEOUT_SEC))
        return 4
    if "error" in answer:
        sys.stderr.write("%s skills/list 报错：%s\n" % (binary, answer["error"]))
        return 5

    lines, failures = [], []
    for group in answer["result"]["data"]:
        # errors 与 skills 是并列的：响应成功不代表这份清单是全的。
        # 有 Skill 解析失败却照常输出剩下的，等于把「少了几项」伪装成「就这几项」。
        for problem in group.get("errors") or []:
            failures.append("%s：%s" % (group.get("cwd", "?"), json.dumps(problem, ensure_ascii=False)
                                        if not isinstance(problem, str) else problem))
        for skill in group.get("skills", []):
            lines.append("%s\t%s\n" % (skill["name"], skill["path"]))
    if failures:
        sys.stderr.write("%s skills/list 报告 %d 项解析失败，这份清单不完整：\n  %s\n"
                         % (binary, len(failures), "\n  ".join(failures)))
        return 6
    for line in lines:
        sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
