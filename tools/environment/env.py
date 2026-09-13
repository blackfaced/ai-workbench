#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Workbench 个人开发环境入口。

四个子命令共用同一份 Profile 解析与同一次观测：

    plan  = observe + diff，只打印
    apply = plan + 对可执行的 diff 真正写入
    check = plan + 断言 diff 为空 + 额外只读断言
    restore --backup <ts> = 按备份 manifest 逐条回滚（只回滚本入口写过的东西：
            受管块只回滚块本身，新建的文件与链接会被删掉；安装之后又被人改过的
            目标默认跳过并报告，确认后才用 --force）

只用标准库，兼容 Python 3.9（两台开发机与 Mac 的系统 python3 都能跑）。
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "profiles")
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
STATE_DIR = os.path.expanduser("~/.ai-workbench/environment")
BACKUP_ROOT = os.path.join(STATE_DIR, "backups")
STATE_PATH = os.path.join(STATE_DIR, "state.json")
MARKER = "ai-workbench:"


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def expand(path):
    return os.path.expanduser(path)


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso(epoch=None):
    when = (datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
            if epoch is not None else datetime.datetime.now(datetime.timezone.utc))
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def die(message):
    sys.stderr.write("错误：%s\n" % message)
    raise SystemExit(2)


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return "(无输出)"


def version_tuple(text):
    return tuple(int(part) for part in re.findall(r"\d+", text or "")[:3])


# --------------------------------------------------------------------------
# 安装记录与备份
# --------------------------------------------------------------------------

def load_state():
    try:
        return json.loads(read_text(STATE_PATH))
    except (IOError, OSError, ValueError):
        return {"components": {}}


def save_state(state):
    if not os.path.isdir(STATE_DIR):
        os.makedirs(STATE_DIR)
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


MANIFEST_VERSION = 2


class Backup(object):
    """一次运行一个备份目录，第一次真正写文件时才创建。

    manifest v2 记三类写入，少记一类 restore 就撤不干净：

        file          普通文件：被替换（existed=true）、被新建（existed=false）
                      或被删除（existed=true 且写入后不存在）
        config_block  只动受管块的文件：额外记块的旧正文与插入方式，
                      restore 因此只回滚块本身，块外内容一个字都不碰
        symlink       符号链接：记链接指向而不是 copy2（copy2 会跟随链接）

    每条在写入完成后由 mark_written() 回填「安装后应有的样子」，
    restore 靠它区分「原样未动」与「安装后又被人改过」。
    """

    def __init__(self):
        self.dir = None
        self.entries = []

    def _ensure_dir(self):
        if self.dir is None:
            # 同一秒内跑两次（回归脚本、连着两条 apply）不能撞名，撞了就崩在半路。
            base = os.path.join(BACKUP_ROOT, utc_stamp())
            candidate, serial = base, 1
            while os.path.exists(candidate):
                candidate = "%s-%d" % (base, serial)
                serial += 1
            self.dir = candidate
            os.makedirs(self.dir)
        return self.dir

    def _flush(self):
        with open(os.path.join(self.dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"version": MANIFEST_VERSION, "created_at": utc_iso(),
                       "entries": self.entries}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def save(self, path, component=None, kind="file", block=None, created_dir=None,
             state_before=None):
        """写入前登记现状。路径不存在也要登记 —— 首装的撤销全靠这条。

        `state_before` 记的是「这次写入之前，安装记录里关于它的那条」：
        更新的回滚要把上一版记录放回去，不能一律销号（销了就变成「不是本入口装的」）。
        """
        self._ensure_dir()
        entry = {
            "component": component,
            "kind": kind,
            "original_path": path,
            "existed": os.path.lexists(path),
            "backup_file": None,
            "sha256": None,
            "mtime": None,
            "link_target": None,
            "created_dir": created_dir,
            "block": block,
            "sha256_after_apply": None,
            "link_after": None,
            "state_before": state_before or {},
        }
        if entry["existed"]:
            if os.path.islink(path):
                entry["kind"] = "symlink"
                entry["link_target"] = os.readlink(path)
            else:
                flat = "%03d_%s" % (len(self.entries), path.lstrip("/").replace("/", "_"))
                shutil.copy2(path, os.path.join(self.dir, flat))
                entry["backup_file"] = flat
                entry["sha256"] = sha256_file(path)
                entry["mtime"] = utc_iso(os.stat(path).st_mtime)
        self.entries.append(entry)
        self._flush()
        return entry

    def mark_written(self, entry):
        path = entry["original_path"]
        if os.path.islink(path):
            entry["link_after"] = os.readlink(path)
        elif os.path.isfile(path):
            entry["sha256_after_apply"] = sha256_file(path)
            if entry.get("block"):
                entry["block"]["applied_body"] = extract_block(
                    read_text(path), entry["block"]["begin"], entry["block"]["end"])
        self._flush()
        return entry


# --------------------------------------------------------------------------
# 命令执行：Profile 里写的命令一律在登录 shell 里跑，PATH 与用户一致
# --------------------------------------------------------------------------

def run_shell(shell, flag, script, cwd=None, timeout=900):
    proc = subprocess.Popen([shell, flag, script], cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = proc.communicate(timeout=timeout)
    return proc.returncode, out.decode("utf-8", "replace")


def split_markers(text):
    """解析批处理输出里的 '##<id>' 分节。"""
    sections = {}
    current = None
    for line in text.splitlines():
        if line.startswith("##"):
            current = line[2:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return dict((key, "\n".join(value).strip()) for key, value in sections.items())


# --------------------------------------------------------------------------
# 计划：一次观测的三种投影共用它
# --------------------------------------------------------------------------

class Plan(object):
    def __init__(self):
        self.changes = []   # (cid, summary, action)  —— apply 能执行
        self.blocked = []   # (cid, summary)          —— 需要人处理，check 判红
        self.notes = []     # (cid, text)             —— 只报告
        self.obs = []       # (cid, [lines])          —— 观测明细

    def observe(self, cid, lines):
        self.obs.append((cid, lines))

    def change(self, cid, summary, action):
        self.changes.append((cid, summary, action))

    def block(self, cid, summary):
        self.blocked.append((cid, summary))

    def note(self, cid, text):
        self.notes.append((cid, text))


class Context(object):
    def __init__(self, profile, profile_name):
        self.profile = profile
        self.name = profile_name
        self.shell = profile.get("shell", "/bin/sh")
        self.state = load_state()
        self.backup = Backup()
        self.resolved = {}
        self.versions = {}
        self.skill_names = None
        self.planned_ids = set()
        self.force = False  # --force：明知目标不是本入口装的，仍接管（覆盖前照常备份）

    def login(self, script, cwd=None):
        return run_shell(self.shell, "-lc", script, cwd=cwd)

    def record(self, cid, entry):
        entry["applied_at"] = utc_iso()
        entry["backup_dir"] = self.backup.dir
        self.state.setdefault("components", {})[cid] = entry

    def backup_save(self, path, component=None, state_keys=None, **kwargs):
        """备份 + 把这次写入之前的安装记录一起存进 manifest。

        `state_keys` 缺省就是 component 自己；历史副本清理那种「manifest 里的名字
        不等于安装记录里的名字」的场景显式传进来。
        """
        components = self.state.get("components", {})
        before = {}
        for key in (state_keys if state_keys is not None else [component]):
            if key in components:
                before[key] = dict(components[key])
        return self.backup.save(path, component=component, state_before=before, **kwargs)

    def declared_skill_dirs(self):
        out = []
        for client, spec in sorted(self.profile.get("clients", {}).items()):
            if spec.get("skills_dir"):
                out.append((client, expand(spec["skills_dir"])))
        return out

    def skill_available(self, name):
        """依赖判定：在本机任一已声明的 Skill 目录里能发现即算满足。"""
        if self.skill_names is None:
            names = set()
            for _client, path in self.declared_skill_dirs():
                if os.path.isdir(path):
                    for entry in os.listdir(path):
                        if os.path.isfile(os.path.join(path, entry, "SKILL.md")):
                            names.add(entry)
            self.skill_names = names
        return name in self.skill_names


# --------------------------------------------------------------------------
# 组件类型 1：config_block
# --------------------------------------------------------------------------

def block_markers(comp):
    prefix = comp.get("comment_prefix", "#")
    return ("%s %s%s BEGIN" % (prefix, MARKER, comp["id"]),
            "%s %s%s END" % (prefix, MARKER, comp["id"]))


def extract_block(text, begin, end):
    lines = text.splitlines()
    if begin not in lines:
        return None
    start = lines.index(begin)
    tail = lines[start + 1:]
    if end not in tail:
        return None
    return "\n".join(tail[:tail.index(end)])


def write_block(path, begin, end, body, insert_before_re, ctx, component):
    exists = os.path.isfile(path)
    lines = read_text(path).splitlines() if exists else []
    previous_body = extract_block("\n".join(lines), begin, end)
    block = [begin] + body.split("\n") + [end]
    inserted_blank_after = False
    if begin in lines and end in lines[lines.index(begin) + 1:]:
        start = lines.index(begin)
        stop = lines.index(end, start + 1)
        lines[start:stop + 1] = block
    elif insert_before_re:
        pattern = re.compile(insert_before_re)
        hit = None
        for index, line in enumerate(lines):
            if pattern.search(line):
                hit = index
                break
        if hit is None:
            # 宁可失败也不要插错位置：dev8c 的守卫位置决定这个块有没有效果。
            raise RuntimeError("insert_before_re %r 在 %s 里没有命中，拒绝盲插" % (insert_before_re, path))
        lines[hit:hit] = block + [""]
        inserted_blank_after = True
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block)
    entry = ctx.backup_save(path, component=component, kind="config_block",
                        block={"begin": begin, "end": end,
                               "previous_body": previous_body,
                               "inserted_blank_after": inserted_blank_after,
                               "applied_body": None})
    tmp = path + ".aiwb-env-tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    if exists:
        shutil.copymode(path, tmp)
    os.replace(tmp, path)
    ctx.backup.mark_written(entry)


def overwrite_guard(ctx, cid, path, actual):
    """写入前先证明「现在这份就是我上次留下的那份」，否则一律停手。

    config_block 与 skill 共用同一条规则，只是「当前内容」取法不同：
    安装记录里没有它 → 不是本入口装的，是别人的东西；
    记录对不上 → 安装之后有人改过。两种情况都不覆盖，交给人决定。
    """
    recorded = ctx.state.get("components", {}).get(cid, {}).get("sha256_after_apply")
    if recorded is None:
        return "%s 已存在，但安装记录里没有它（不是本入口装的），不覆盖" % path
    if recorded != sha256_text(actual):
        return "%s 与安装记录不一致（安装后被改过），不覆盖" % path
    return None


def guarded(ctx, plan, cid, path, actual):
    """overwrite_guard 的带逃生口版本：--force 时降级为一条提示。

    没有逃生口的话，任何「装机前就已存在同名文件」的机器都会永久卡在 blocked：
    入口既不肯覆盖，也没有别的接管路径。--force 仍走完整备份，restore 撤得回去。
    """
    reason = overwrite_guard(ctx, cid, path, actual)
    if reason and ctx.force:
        plan.note(cid, "--force 接管：%s（覆盖前仍会备份）" % reason)
        return None
    return reason


def plan_config_block(comp, ctx, plan):
    cid = comp["id"]
    path = expand(comp["path"])
    begin, end = block_markers(comp)
    desired = "\n".join(comp["body"])
    text = read_text(path) if os.path.isfile(path) else ""
    current = extract_block(text, begin, end)
    plan.observe(cid, [
        "文件：%s%s" % (path, "" if os.path.isfile(path) else "（不存在）"),
        "受管块：%s" % ("存在" if current is not None else "缺失"),
        "为什么受管：%s" % comp.get("why", "(未写)"),
    ])
    if current is not None and current == desired:
        plan.note(cid, "受管块已是目标形态")
        return
    if current is not None:
        reason = guarded(ctx, plan, cid, path, current)
        if reason:
            plan.block(cid, reason)
            return
        summary = "更新受管块 → %s" % path
    else:
        where = ("插入到 /%s/ 匹配的首行之前" % comp["insert_before_re"]
                 if comp.get("insert_before_re") else "追加到文件末尾")
        summary = "写入受管块 → %s（%s）" % (path, where)

    def action():
        write_block(path, begin, end, desired, comp.get("insert_before_re"), ctx, cid)
        ctx.record(cid, {"path": path, "sha256_after_apply": sha256_text(desired),
                         "version": None, "owner": comp.get("owner", "ai-workbench")})

    plan.change(cid, summary, action)


# --------------------------------------------------------------------------
# 组件类型 2：tool
# --------------------------------------------------------------------------

def probe_tools(ctx, tools):
    """双 shell 上下文各跑一次批处理解析，再在登录 shell 里批量取版本。"""
    if not tools:
        return
    resolve = "".join("printf '##%s\\n'; command -v %s 2>/dev/null || true\n"
                      % (t["id"], shlex.quote(t["bin"])) for t in tools)
    _rc, login_out = run_shell(ctx.shell, "-lc", resolve)
    _rc, plain_out = run_shell(ctx.shell, "-c", resolve)
    login = split_markers(login_out)
    plain = split_markers(plain_out)
    for tool in tools:
        ctx.resolved[tool["id"]] = {
            "login": first_line(login.get(tool["id"], "")).replace("(无输出)", ""),
            "plain": first_line(plain.get(tool["id"], "")).replace("(无输出)", ""),
        }
    versions = "".join("printf '##%s\\n'; { %s ; } 2>&1 | head -n 3\n"
                       % (t["id"], t["version_cmd"]) for t in tools if t.get("version_cmd"))
    if versions:
        _rc, out = run_shell(ctx.shell, "-lc", versions)
        ctx.versions.update(split_markers(out))


def find_on_disk(ctx, name):
    """PATH 解析失败时，看 Profile 声明的用户 bin 目录里是否真有这个可执行文件。

    「未安装」与「当前 shell 不可见」是两个相反的结论（dev8c 就是后者），
    ADR 要求严格区分。目录由 Profile 的 user_bin_dirs 声明，代码里不写机器路径。
    """
    for raw in ctx.profile.get("user_bin_dirs", []):
        candidate = os.path.join(expand(raw), name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def plan_tool(comp, ctx, plan):
    cid = comp["id"]
    resolved = ctx.resolved.get(cid, {})
    login = resolved.get("login", "")
    plain = resolved.get("plain", "")
    output = ctx.versions.get(cid, "")
    version = None
    if comp.get("version_re"):
        match = re.search(comp["version_re"], output)
        if match:
            version = match.group(1) if match.groups() else match.group(0)
    lines = [
        "bin：%s%s" % (comp["bin"], "（显式路径，绕开 PATH 优先级）" if comp.get("explicit_path") else ""),
        "owner：%s（required=%s）" % (comp["owner"], bool(comp.get("required"))),
        "登录 shell（%s -lc）：%s" % (ctx.shell, login or "未找到"),
        "非交互 shell（%s -c）：%s" % (ctx.shell, plain or "未找到"),
        "版本：%s ← %s" % (version or "未取到", first_line(output)),
    ]
    if comp.get("note"):
        lines.append("note：%s" % comp["note"])

    def reprobe_version():
        """装完 / 升完再问一次机器，不拿计划当结果。"""
        if not comp.get("version_cmd"):
            return None
        _rc, text = ctx.login(comp["version_cmd"])
        if comp.get("version_re"):
            hit = re.search(comp["version_re"], text)
            if hit:
                return hit.group(1) if hit.groups() else hit.group(0)
        return first_line(text)

    def run_channel(cmd, kind):
        def action():
            code, out = ctx.login(cmd)
            sys.stdout.write(out)
            if code != 0:
                raise RuntimeError("%s 失败（rc=%d）：%s" % (kind, code, cmd))
            seen, _ = ctx.login("command -v %s" % shlex.quote(comp["bin"]))
            if seen != 0 and not comp.get("explicit_path"):
                raise RuntimeError("%s 跑完了，但登录 shell 仍解析不到 %s" % (kind, comp["bin"]))
            after = reprobe_version()
            if comp.get("min_version") and after and version_tuple(after) \
                    and version_tuple(after) < version_tuple(comp["min_version"]):
                raise RuntimeError("%s 后仍是 %s，没达到 min_version %s：这个渠道无效，别重复跑"
                                   % (kind, after, comp["min_version"]))
            ctx.record(cid, {"path": login or comp["bin"], "sha256_after_apply": None,
                             "version": after, "owner": comp["owner"]})
        return action

    def install_action(cmd):
        return run_channel(cmd, "install_cmd")

    if not login and not plain:
        on_disk = None if comp.get("explicit_path") else find_on_disk(ctx, comp["bin"])
        if on_disk:
            lines.append("结论：已安装于 %s，但两种 shell 都解析不到 —— 是 PATH 入口问题，不是缺软件" % on_disk)
            plan.observe(cid, lines)
            plan.block(cid, "已安装（%s）但登录 shell 与非交互 shell 都不可见："
                            "等受管 PATH 块生效后重跑，不要再装第二份" % on_disk)
            return
        lines.append("结论：未安装")
        plan.observe(cid, lines)
        via = comp.get("install_via")
        if comp.get("install_cmd"):
            plan.change(cid, "安装 %s：%s" % (cid, comp["install_cmd"]), install_action(comp["install_cmd"]))
        elif via and via in ctx.planned_ids:
            plan.note(cid, "缺失：安装渠道是组件 %s，本次计划已包含它，由它负责装" % via)
        elif via:
            plan.block(cid, "缺失：安装渠道是组件 %s，但本次运行没有包含该组件（--only 把它挡在外面了）" % via)
        elif comp.get("required"):
            plan.block(cid, "必需工具缺失，且 Profile 未登记已验证的安装渠道，需要人工处理")
        else:
            plan.note(cid, "可选工具未安装：按项目需要再装，不因为另一台机器有就装")
        return

    if bool(login) != bool(plain):
        plan.block(cid, "只在一种 shell 上下文可见（登录=%s / 非交互=%s）" % (login or "无", plain or "无"))
    if comp.get("identity_re") and not re.search(comp["identity_re"], output, re.M):
        plan.block(cid, "身份断言失败：identity_re=%r 未命中版本输出 %r" % (comp["identity_re"], first_line(output)))
    else:
        lines.append("身份断言：%s ✓" % comp.get("identity_re", "(未声明)"))
    if comp.get("min_version"):
        if not version:
            plan.block(cid, "声明了 min_version %s，却取不到版本号：先修 version_cmd/version_re" % comp["min_version"])
        elif version_tuple(version) < version_tuple(comp["min_version"]):
            if comp.get("update_cmd"):
                plan.change(cid, "更新 %s：%s → ≥ %s（%s）"
                            % (cid, version, comp["min_version"], comp["update_cmd"]),
                            run_channel(comp["update_cmd"], "update_cmd"))
            elif comp.get("required"):
                plan.block(cid, "版本 %s 低于 min_version %s，且 Profile 未登记已验证的更新渠道"
                           % (version, comp["min_version"]))
            else:
                plan.note(cid, "可选工具版本 %s 低于 min_version %s，且没有已验证的更新渠道"
                          % (version, comp["min_version"]))
    if comp.get("origin_cmd"):
        _rc, origin = ctx.login(comp["origin_cmd"])
        origin = origin.strip()
        lines.append("origin：%s" % (first_line(origin)))
        if comp.get("origin_must_not_match") and re.search(comp["origin_must_not_match"], origin):
            summary = "来源命中禁止模式 %r，重装到稳定路径：%s" % (comp["origin_must_not_match"], comp.get("install_cmd"))
            if comp.get("install_cmd"):
                plan.change(cid, summary, install_action(comp["install_cmd"]))
            else:
                plan.block(cid, summary)
    plan.observe(cid, lines)


# --------------------------------------------------------------------------
# 组件类型 3：skill（一份正文真源 + 每客户端 frontmatter）
# --------------------------------------------------------------------------

def render_skill(frontmatter, body):
    return frontmatter.rstrip("\n") + "\n\n" + body.lstrip("\n")


def plan_managed_file(ctx, plan, lines, label, sub, path, desired, version, summary):
    """一个受管文件的三段式：观测 → 归属证明 → 写入计划。SKILL.md 与附带文件共用。"""
    link = os.path.islink(path)
    actual = None if link else (read_text(path) if os.path.isfile(path) else None)
    lines.append("%s：%s %s" % (label, path,
                               ("符号链接 -> %s" % os.readlink(path)) if link else
                               ("一致" if actual == desired else
                                ("待更新" if actual is not None else "待安装"))))
    if not link and actual == desired:
        return
    # 与 config_block 同一条规则：目标已存在时，先证明这份是我上次留下的。
    if link:
        reason = link_guard(ctx, plan, sub, path)
    elif actual is not None:
        reason = guarded(ctx, plan, sub, path, actual)
    else:
        reason = None
    if reason:
        plan.block(sub, reason)
        return
    plan.change(sub, "%s → %s" % (summary, path),
                _file_writer(ctx, sub, path, desired, version))


def link_guard(ctx, plan, cid, path):
    """目标本身是符号链接时的规则：默认不接管。

    顺着链接写，改的是别人那个文件，而备份只存得下「链接指向哪」——
    restore 之后会一脸无辜地报成功，被改写的那份原内容却已经没了。
    --force 时改为替换链接自己（备份 kind=symlink，restore 把链接接回去），
    绝不去动它指向的文件。
    """
    reason = "%s 是符号链接（-> %s），顺着它写会改到链接之外的文件，不接管" % (path, os.readlink(path))
    if ctx.force:
        plan.note(cid, "--force：替换符号链接本身而不是它指向的文件 —— %s（原链接已备份）" % reason)
        return None
    return reason


def plan_skill(comp, ctx, plan):
    cid = comp["id"]
    name = comp["name"]
    body = read_text(os.path.join(REPO_ROOT, comp["body"]))
    lines = [
        "正文真源：%s" % comp["body"],
        "source=%s revision=%s" % (comp.get("source"), comp.get("revision")),
        "depends_on=%s" % (comp.get("depends_on") or []),
    ]
    desired_map = {}   # 本次运行结束后受管副本「应该」长什么样，历史副本判重用它
    missing = [dep for dep in comp.get("depends_on", []) if not ctx.skill_available(dep)]
    if missing:
        lines.append("结论：跳过（依赖缺失）")
        plan.observe(cid, lines)
        plan.note(cid, "跳过安装：依赖 %s 未在本机任何已声明 Skill 目录中发现，不装跑不起来的 Skill" % missing)
        return

    for client in sorted(comp["clients"]):
        spec = comp["clients"][client]
        skill_dir = os.path.join(expand(spec["dir"]), name)
        target = os.path.join(skill_dir, "SKILL.md")
        desired = render_skill(read_text(os.path.join(REPO_ROOT, spec["frontmatter"])), body)
        desired_map[target] = desired
        plan_managed_file(ctx, plan, lines, client, "%s:%s" % (cid, client), target, desired,
                          comp.get("revision"),
                          "渲染 %s 的 %s 客户端正文" % (name, client))
        # 附带文件：客户端专属的界面 / 策略描述（如 Codex 的 agents/openai.yaml）。
        # 不带上它，收敛到单副本时会把 allow_implicit_invocation:false 这类策略静悄悄丢掉。
        for rel in sorted(spec.get("files", {})):
            fpath = os.path.join(skill_dir, rel)
            want = read_text(os.path.join(REPO_ROOT, spec["files"][rel]))
            desired_map[fpath] = want
            plan_managed_file(ctx, plan, lines, client, "%s:%s:%s" % (cid, client, rel),
                              fpath, want, comp.get("revision"),
                              "写入 %s 的附带文件" % name)
        if spec.get("link_from"):
            link = os.path.join(expand(spec["link_from"]), name)
            want = os.path.relpath(skill_dir, os.path.dirname(link))
            have = os.readlink(link) if os.path.islink(link) else None
            lines.append("%s：符号链接 %s -> %s" % (client, link, have or "缺失"))
            if have != want:
                if have is None and os.path.exists(link):
                    plan.block("%s:%s" % (cid, client), "%s 已存在且不是符号链接，不覆盖" % link)
                else:
                    plan.change("%s:%s-link" % (cid, client),
                                "建立符号链接 %s -> %s" % (link, want),
                                _link_writer(ctx, cid, client, link, want))

    # 历史副本：同一个 Skill 在多个客户端目录里各放一份，会被聚合发现成重名。
    # 只清 Profile 显式点名的路径，且只在「里面每个文件都能在受管副本里找到一模一样的对应物」时动手 ——
    # 换句话说：删掉不丢任何内容。有一个文件对不上，就整条交给人。
    managed = [os.path.join(expand(spec["dir"]), name) for spec in comp["clients"].values()]
    for index, raw in enumerate(comp.get("stale_copies", [])):
        stale_dir = expand(raw)
        sub = "%s:stale%d" % (cid, index)
        if os.path.islink(stale_dir):
            # 关键：符号链接要按链接删。顺着它 listdir/unlink 会删到受管副本的真身。
            lines.append("历史副本 %s：是符号链接 -> %s，删链接即可" % (stale_dir, os.readlink(stale_dir)))
            plan.change(sub, "删除历史符号链接（不碰它指向的真身）：%s" % stale_dir,
                        _stale_link_remover(ctx, sub, stale_dir))
            continue
        if not os.path.exists(stale_dir):
            lines.append("历史副本 %s：已不存在 ✓" % stale_dir)
            continue
        files = sorted(relative_files(stale_dir))
        lines.append("历史副本 %s：仍在（内含 %s）" % (stale_dir, files))
        orphans = [rel for rel in files
                   if not has_identical_copy(stale_dir, rel, managed, desired_map)
                   and not recorded_as_ours(ctx, os.path.join(stale_dir, rel))]
        if orphans:
            reason = ("%s 里的 %s 在受管副本里没有内容相同的对应物，删了会丢东西，交给人处理"
                      % (stale_dir, orphans))
            if not ctx.force:
                plan.block(sub, reason)
                continue
            plan.note(sub, "--force 删除历史副本：%s（每个文件仍逐一备份，restore 撤得回）" % reason)
        plan.change(sub, "删除历史副本（%d 个文件，%s，仍逐一备份）：%s"
                    % (len(files), "--force 指定" if orphans else "内容都在受管副本里", stale_dir),
                    _stale_remover(ctx, sub, stale_dir, files))
    plan.observe(cid, lines)


def relative_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            yield os.path.relpath(os.path.join(dirpath, filename), root)


def has_identical_copy(stale_dir, rel, managed_dirs, desired_map):
    """受管副本里有没有一份逐字节相同的它。

    要看「本次运行写完之后」的形态：附带文件与历史副本清理常常在同一次 apply 里，
    只看磁盘现状会让第一次 apply 永远判 block，第二次才肯删。
    """
    src = os.path.join(stale_dir, rel)
    if os.path.islink(src):
        return False  # 链接的语义不是内容，别自作主张
    digest = sha256_file(src)
    for managed_dir in managed_dirs:
        twin = os.path.join(managed_dir, rel)
        if twin in desired_map:
            if sha256_text(desired_map[twin]) == digest:
                return True
            continue
        if os.path.isfile(twin) and not os.path.islink(twin) and sha256_file(twin) == digest:
            return True
    return False


def recorded_as_ours(ctx, path):
    """这份历史副本是不是本入口自己写下、之后没人动过的。

    是的话删它不丢任何东西 —— 内容随时能从仓库重新渲染出来，
    不必因为「新版正文多了一行 author」就把清理永久卡在 block。
    """
    if not os.path.isfile(path) or os.path.islink(path):
        return False
    digest = sha256_file(path)
    for entry in ctx.state.get("components", {}).values():
        if entry.get("path") == path and entry.get("sha256_after_apply") == digest:
            return True
    return False


def _stale_link_remover(ctx, sub, link):
    def action():
        entry = ctx.backup_save(link, component=sub, kind="symlink")
        os.unlink(link)
        ctx.backup.mark_written(entry)
        ctx.state.get("components", {}).pop(sub, None)
    return action


def _stale_remover(ctx, sub, stale_dir, files):
    def action():
        for rel in files:
            target = os.path.join(stale_dir, rel)
            owners = [k for k, v in ctx.state.get("components", {}).items()
                      if v.get("path") == target]
            entry = ctx.backup_save(target, component="%s:%s" % (sub, rel), kind="file",
                                    state_keys=owners)
            os.unlink(target)
            ctx.backup.mark_written(entry)
            # 旧版 Profile 可能把这个副本记成了一个正式组件，一并销号（回滚时按 state_before 复原）
            for cid in owners:
                ctx.state["components"].pop(cid)
        for dirpath, _dirnames, _filenames in sorted(os.walk(stale_dir), reverse=True):
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        ctx.state.get("components", {}).pop(sub, None)
    return action


def _file_writer(ctx, sub, path, content, version):
    def action():
        parent = os.path.dirname(path)
        created_dir = None if os.path.isdir(parent) else parent
        if created_dir:
            os.makedirs(parent)
        entry = ctx.backup_save(path, component=sub, kind="file", created_dir=created_dir)
        if os.path.islink(path):
            # 关键：open(path,"w") 会顺着链接改写它指向的那个文件，而备份只存了链接本身，
            # restore 于是「成功」了却还不回原内容。改成替换链接自己。
            os.unlink(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        ctx.backup.mark_written(entry)
        ctx.record(sub, {"path": path, "sha256_after_apply": sha256_text(content),
                         "version": version, "owner": "ai-workbench-repo"})
    return action


def _link_writer(ctx, cid, client, link, want):
    def action():
        parent = os.path.dirname(link)
        created_dir = None if os.path.isdir(parent) else parent
        if created_dir:
            os.makedirs(parent)
        entry = ctx.backup_save(link, component="%s:%s-link" % (cid, client),
                                kind="symlink", created_dir=created_dir)
        if os.path.islink(link):
            os.unlink(link)
        os.symlink(want, link)
        ctx.backup.mark_written(entry)
        ctx.record("%s:%s-link" % (cid, client),
                   {"path": link, "sha256_after_apply": None, "version": None,
                    "owner": "ai-workbench-repo"})
    return action


# --------------------------------------------------------------------------
# 组件类型 4：installer（包住已存在的安装器）
# --------------------------------------------------------------------------

def plan_installer(comp, ctx, plan):
    cid = comp["id"]
    # installer 的命令里可能带仓库内相对路径（如 --file=packages/macos.Brewfile），
    # 固定在本目录执行，使其与调用方的 CWD 无关。
    code, out = ctx.login(comp["check_cmd"], cwd=HERE)
    plan.observe(cid, [
        "owner：%s" % comp["owner"],
        "check_cmd：%s → rc=%d" % (comp["check_cmd"], code),
        "输出：%s" % first_line(out),
        "note：%s" % comp.get("note", ""),
    ])
    if code == 0:
        plan.note(cid, "安装器报告无缺项")
        return

    def action():
        rc, text = ctx.login(comp["apply_cmd"], cwd=HERE)
        sys.stdout.write(text)
        if rc != 0:
            raise RuntimeError("apply_cmd 失败（rc=%d）：%s" % (rc, comp["apply_cmd"]))
        ctx.record(cid, {"path": comp["check_cmd"], "sha256_after_apply": None,
                         "version": None, "owner": comp["owner"]})

    plan.change(cid, "运行安装器：%s" % comp["apply_cmd"], action)


PLANNERS = {
    "config_block": plan_config_block,
    "tool": plan_tool,
    "skill": plan_skill,
    "installer": plan_installer,
}


def build_plan(ctx, only):
    components = [c for c in ctx.profile["components"] if not only or c["id"] in only]
    if only:
        unknown = sorted(set(only) - set(c["id"] for c in components))
        if unknown:
            die("--only 里有未知 id：%s" % ", ".join(unknown))
    probe_tools(ctx, [c for c in components if c["type"] == "tool"])
    ctx.planned_ids = set(c["id"] for c in components)
    plan = Plan()
    for comp in components:
        planner = PLANNERS.get(comp["type"])
        if planner is None:
            die("未知组件类型 %r（id=%s）" % (comp["type"], comp["id"]))
        planner(comp, ctx, plan)
    return plan


# --------------------------------------------------------------------------
# 内建只读检查 1：hook 重复
# --------------------------------------------------------------------------

def normalize_command(text):
    """比较前剔除明确的机器路径元数据，避免把正常差异误报成漂移。"""
    text = text.strip().strip("'\"")
    text = text.replace(os.path.expanduser("~"), "~")
    # lazy: 只归一化已实测存在的 hash 段形态（~/.trae/l1/<hash>/），够用；出现新形态再加。
    text = re.sub(r"/[0-9a-f]{8,}/", "/<hash>/", text)
    return re.sub(r"\s+", " ", text)


def read_hooks(path):
    """返回 [(event, matcher, 原始 command)]。"""
    hooks = []
    if not os.path.isfile(path):
        return hooks
    if path.endswith(".json"):
        try:
            data = json.loads(read_text(path))
        except ValueError as exc:
            return [("(解析失败)", str(exc), path)]
        for event, groups in sorted((data.get("hooks") or {}).items()):
            for group in groups or []:
                matcher = group.get("matcher", "(无 matcher)")
                for entry in group.get("hooks") or []:
                    hooks.append((event, matcher, entry.get("command", "")))
        return hooks
    # lazy: TOML 用行扫描而不是完整解析器 —— Python 3.9 没有 tomllib，这个检查只读只报告。
    event = None
    matcher = "(无 matcher)"
    in_hooks_table = False
    for line in read_text(path).splitlines():
        head = re.match(r"^\[\[hooks\.([A-Za-z]+)(\.hooks)?\]\]", line.strip())
        if head:
            if head.group(2):
                in_hooks_table = True
            else:
                event = head.group(1)
                matcher = "(无 matcher)"
                in_hooks_table = False
            continue
        if line.strip().startswith("[") and not head:
            # 进入别的 table，hook 上下文结束
            event = None
            in_hooks_table = False
        matched = re.match(r"^\s*matcher\s*=\s*(.+)$", line)
        if matched and event and not in_hooks_table:
            matcher = matched.group(1).strip()
        command = re.match(r"^\s*command\s*=\s*(.+)$", line)
        if command and event and in_hooks_table:
            hooks.append((event, matcher, command.group(1).strip()))
    return hooks


def check_hooks(ctx, report):
    report.section("HOOK 重复检查（只读，不改写第三方安装器正文）")
    duplicates = 0
    for client, spec in sorted(ctx.profile.get("clients", {}).items()):
        for raw in spec.get("hook_files", []):
            path = expand(raw)
            hooks = read_hooks(path)
            if not os.path.isfile(path):
                report.line("  %s %s：文件不存在" % (client, raw))
                continue
            seen = {}
            for event, matcher, command in hooks:
                key = (event, normalize_command(command))
                seen.setdefault(key, []).append(matcher)
            report.line("  %s %s：%d 条 hook / %d 个 (event, 归一化 command) 组合"
                        % (client, raw, len(hooks), len(seen)))
            for (event, command), matchers in sorted(seen.items()):
                if len(matchers) > 1:
                    duplicates += 1
                    report.line("    重复 ✗ %s ×%d matcher=%s command=%s"
                                % (event, len(matchers), matchers, command))
    for note in ctx.profile.get("hook_notes", []):
        report.line("  规则来源说明：%s" % note)
    report.line("  重复项合计：%d" % duplicates)
    return duplicates


# --------------------------------------------------------------------------
# 内建只读检查 2：Skill 发现
# --------------------------------------------------------------------------

def parse_frontmatter(path):
    lines = read_text(path).splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "缺少 frontmatter 起始 ---"
    data = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return data, None
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return None, "frontmatter 未闭合"


def check_skills(ctx, report):
    report.section("SKILL 发现检查（安装目录数 ≠ 客户端可发现数 ≠ 本轮实际调用）")
    errors = check_skill_dir_hygiene(ctx, report)
    errors += check_skill_duplicates(ctx, report)
    for note in ctx.profile.get("skill_notes", []):
        report.line("  判断：%s" % note)
    report.line("  本轮实际调用：未观测 —— env.py 不驱动客户端会话，调用量需在客户端里看")
    report.line("  Skill 发现错误合计：%d" % errors)
    return errors


def check_skill_dir_hygiene(ctx, report):
    """目录级卫生：断链、缺 SKILL.md、frontmatter 解析、目录名与 name 是否一致。"""
    errors = 0
    for client, path in ctx.declared_skill_dirs():
        if not os.path.isdir(path):
            report.line("  %s %s：目录不存在" % (client, path))
            continue
        entries = sorted(e for e in os.listdir(path) if not e.startswith("."))
        healthy = []
        for name in entries:
            full = os.path.join(path, name)
            if os.path.islink(full) and not os.path.exists(full):
                errors += 1
                report.line("    断链 ✗ %s -> %s" % (full, os.readlink(full)))
                continue
            skill_md = os.path.join(full, "SKILL.md")
            if not os.path.isfile(skill_md):
                report.line("    非 Skill 目录（无 SKILL.md，不计入可发现）：%s" % name)
                continue
            data, err = parse_frontmatter(skill_md)
            if err:
                errors += 1
                report.line("    解析错误 ✗ %s：%s" % (name, err))
                continue
            if data.get("name") and data["name"] != name:
                errors += 1
                report.line("    name 不一致 ✗ 目录=%s frontmatter=%s" % (name, data["name"]))
                continue
            healthy.append(name)
        report.line("  %s %s：安装目录 %d 项 / 结构完好 %d 项" % (client, path, len(entries), len(healthy)))
    return errors


def discover_client_skills(ctx, client, spec):
    """返回 (来源说明, {name: [路径...]}, 失败原因)。

    重名只能在「客户端自己看到的全集」里判断：Codex 与 Trae 都会把 ~/.agents/skills
    和自己的目录合到一起（2026-09-07 三台机器用 app-server skills/list 实测），
    所以按单个目录各扫各的必然漏报。优先问客户端，问不到才退回聚合目录扫描。
    """
    cmd = spec.get("discovery_cmd")
    if cmd:
        code, out = ctx.login(cmd, cwd=HERE)
        if code != 0:
            return None, None, "原生发现失败（rc=%d）：%s" % (code, first_line(out))
        found = {}
        for line in out.splitlines():
            if "\t" not in line:
                continue
            name, path = line.split("\t", 1)
            found.setdefault(name.strip(), []).append(path.strip())
        return "客户端原生发现（%s）" % cmd, found, None
    dirs = spec.get("discovery_dirs")
    if not dirs:
        return None, None, None  # 这个条目只是个共享目录，没有独立客户端
    found = {}
    for raw in dirs:
        root = expand(raw)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            skill_md = os.path.join(root, name, "SKILL.md")
            if os.path.isfile(skill_md):
                found.setdefault(name, []).append(skill_md)
    return "聚合目录扫描（%s）" % ", ".join(dirs), found, None


def check_skill_duplicates(ctx, report):
    errors = 0
    for client, spec in sorted(ctx.profile.get("clients", {}).items()):
        source, found, failure = discover_client_skills(ctx, client, spec)
        if failure:
            errors += 1
            report.line("  %s：无法确认可发现集合 ✗ %s" % (client, failure))
            continue
        if found is None:
            continue
        if spec.get("require_profile_skills"):
            expected = {c["name"] for c in ctx.profile["components"] if c["type"] == "skill"}
            missing = sorted(expected - set(found))
            if missing:
                errors += 1
                report.line("  %s：缺少 Profile Skill ✗ %s" % (client, ", ".join(missing)))
        if spec.get("discovery_format") == "commands":
            report.line("  %s：原生命令发现 %d 项（ACP 不提供源文件路径，不能证明文件归属或实际执行）"
                        % (client, len(found)))
            if "README" in found:
                report.line("    额外原生命令 skill:README：保留上游索引，不计入第一方 Skill 验收，不修改文件")
            # Names are the only native identity; do not fabricate source paths.
            for name, commands in sorted(found.items()):
                if len(commands) != 1:
                    errors += 1
                    report.line("    重复命令 ✗ %s" % name)
            continue
        dups = 0
        for name in sorted(found):
            paths = found[name]
            realpaths = sorted(set(os.path.realpath(p) for p in paths))
            if len(realpaths) > 1:
                dups += 1
                errors += 1
                report.line("    重名 ✗ %s 同时被发现于：%s" % (name, realpaths))
            elif len(paths) > 1:
                report.line("    同一目标的别名（不算重复，只提示）：%s -> %s" % (name, realpaths[0]))
        report.line("  %s：可发现 %d 项 / 重名 %d 项 —— %s" % (client, len(found), dups, source))
    return errors


# --------------------------------------------------------------------------
# 内建只读检查 3：用户自定义 PATH 行（只报告）
# lazy: 用 Profile 声明的 grep 报告代替静态说明文字 —— 静态文字是断言，不是观测；无需跟进。
# --------------------------------------------------------------------------

def check_path_lines(ctx, report):
    reports = ctx.profile.get("path_line_reports", [])
    if not reports:
        return
    report.section("用户自定义 PATH 行（只报告，不改写）")
    for item in reports:
        path = expand(item["file"])
        if not os.path.isfile(path):
            report.line("  %s：不存在" % path)
            continue
        hits = [(no, line.strip()) for no, line in enumerate(read_text(path).splitlines(), 1)
                if re.search(item["pattern"], line) and "PATH" in line
                and not line.strip().startswith("#")]
        report.line("  %s：命中 /%s/ 的 PATH 行 %d 条 —— %s"
                    % (path, item["pattern"], len(hits), item.get("why", "")))
        for no, line in hits:
            report.line("    第 %d 行：%s" % (no, line))


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

class Report(object):
    def __init__(self):
        self.lines = []

    def section(self, title):
        self.lines.append("")
        self.lines.append("== %s" % title)

    def line(self, text):
        self.lines.append(text)

    def flush(self):
        sys.stdout.write("\n".join(self.lines) + "\n")
        self.lines = []


def print_plan(ctx, plan, verb, report):
    report.line("AI Workbench 环境入口 · %s · profile=%s · host=%s · shell=%s"
                % (verb, ctx.name, socket.gethostname().split(".")[0], ctx.shell))
    report.section("观测（plan / apply / check 共用同一次）")
    for cid, lines in plan.obs:
        report.line("  [%s]" % cid)
        for line in lines:
            report.line("    %s" % line)
    report.section("待改动 %d 项" % len(plan.changes))
    for cid, summary, _action in plan.changes:
        report.line("  ~ %s：%s" % (cid, summary))
    if not plan.changes:
        report.line("  （无）")
    report.section("需要人处理 %d 项" % len(plan.blocked))
    for cid, summary in plan.blocked:
        report.line("  ! %s：%s" % (cid, summary))
    if not plan.blocked:
        report.line("  （无）")
    report.section("只报告 %d 项" % len(plan.notes))
    for cid, text in plan.notes:
        report.line("  - %s：%s" % (cid, text))
    if not plan.notes:
        report.line("  （无）")


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def pick_profile(name):
    if name:
        return name
    system = platform.system()
    host = socket.gethostname().split(".")[0]
    compatible = []
    for entry in sorted(os.listdir(PROFILE_DIR)):
        if not entry.endswith(".json"):
            continue
        profile = json.loads(read_text(os.path.join(PROFILE_DIR, entry)))
        if profile.get("os") != system:
            continue
        compatible.append(entry[:-len(".json")])
        for _alias, spec in (profile.get("hosts") or {}).items():
            if spec.get("match_hostname") == host:
                return entry[:-len(".json")]
    if system == "Darwin" and len(compatible) == 1:
        return compatible[0]
    die("判不出 profile：system=%s hostname=%s，请显式 --profile" % (system, host))


def load_profile(name):
    path = os.path.join(PROFILE_DIR, name + ".json")
    if not os.path.isfile(path):
        die("没有这个 profile：%s" % path)
    return json.loads(read_text(path))


def cmd_run(args, verb):
    name = pick_profile(args.profile)
    ctx = Context(load_profile(name), name)
    ctx.force = bool(getattr(args, "force", False))
    plan = build_plan(ctx, set(args.only or []))
    report = Report()
    print_plan(ctx, plan, verb, report)

    exit_code = 0
    if verb == "apply":
        report.section("apply 执行")
        if plan.blocked:
            # 需要人处理的项本身不产生写入（每个 planner 都是 block 后即 return），
            # 所以照常执行可执行的改动，只用非 0 退出码把 blocked 项报出来。
            # 反过来（有 blocked 就一个字都不写）会让 dev8c 这类机器死锁：
            # 修 PATH 的受管块永远因为它自己造成的「工具不可见」而写不进去。
            report.line("  注意：有 %d 项需要人处理（上面的 ! 项）；它们不产生写入，"
                        "本次仍执行可执行的改动，最后以 rc=1 收尾" % len(plan.blocked))
            exit_code = 1
        if not plan.changes:
            report.line("  无变更（幂等）")
        for cid, summary, action in plan.changes:
            report.line("  → %s：%s" % (cid, summary))
            report.flush()
            try:
                action()
            except RuntimeError as exc:
                sys.stdout.write("  ✗ %s 中止：%s\n" % (cid, exc))
                save_state(ctx.state)  # 保留已成功项的记录
                return 1
        if plan.changes:
            save_state(ctx.state)
            report.line("  备份目录：%s" % (ctx.backup.dir or "（本次未改动需备份的文件）"))
            report.line("  安装记录：%s" % STATE_PATH)
    elif verb == "check":
        duplicates = check_hooks(ctx, report)
        errors = check_skills(ctx, report)
        check_path_lines(ctx, report)
        report.section("check 断言")
        report.line("  待改动=%d 需人处理=%d hook 重复=%d Skill 发现错误=%d"
                    % (len(plan.changes), len(plan.blocked), duplicates, errors))
        report.line("  说明：配置回滚由 restore 保证；外部软件的降级能力取决于其安装器，本入口不承诺降级")
        if plan.changes or plan.blocked or duplicates or errors:
            report.line("  结论：有漂移 ✗")
            exit_code = 1
        else:
            report.line("  结论：与 Profile 一致 ✓")
    report.flush()
    return exit_code


def current_shape(path):
    """当前这个路径长什么样，用与 manifest 同一套词汇描述。"""
    if os.path.islink(path):
        return ("symlink", os.readlink(path))
    if os.path.isfile(path):
        return ("file", sha256_file(path))
    if os.path.isdir(path):
        return ("dir", None)
    return ("absent", None)


def restore_guard(entry):
    """还原前先证明「现在这份还是 apply 刚写完的那份」，否则不动它。

    这是 restore 不吃掉安装后新增内容的唯一保证：形态对不上就跳过，
    人看过之后再用 --force。config_block 另有更细的块级判断。
    """
    path = entry["original_path"]
    kind, value = current_shape(path)
    if entry.get("link_after") is not None:
        if kind == "symlink" and value == entry["link_after"]:
            return None
        return "当前是 %s（期望符号链接 -> %s）" % (kind, entry["link_after"])
    if entry.get("sha256_after_apply") is not None:
        if kind == "file" and value == entry["sha256_after_apply"]:
            return None
        return "当前 sha256=%s，与安装后记录 %s 不一致" % (value or kind, entry["sha256_after_apply"][:12])
    # 安装后为「不存在」：本入口删掉过它（历史副本清理）
    if kind == "absent":
        return None
    return "当前是 %s，但安装后本应不存在" % kind


def restore_config_block(entry, path, force, log):
    block = entry["block"]
    text = read_text(path) if os.path.isfile(path) else None
    if text is None:
        log("    文件已不存在，跳过")
        return False
    body = extract_block(text, block["begin"], block["end"])
    if body is None:
        log("    受管块已不在文件里，无需回滚")
        return False
    if block.get("applied_body") is not None and body != block["applied_body"] and not force:
        log("    块内容与安装后记录不一致（安装后被改过），跳过；确认要覆盖再加 --force")
        return False
    lines = text.splitlines()
    start = lines.index(block["begin"])
    stop = lines.index(block["end"], start + 1)
    if block["previous_body"] is None:
        cut_to = stop + 1
        if block.get("inserted_blank_after") and cut_to < len(lines) and not lines[cut_to].strip():
            cut_to += 1  # 连同当初为它插入的那个空行一起撤掉
        del lines[start:cut_to]
        log("    删除受管块（安装前它不存在）")
    else:
        lines[start:stop + 1] = [block["begin"]] + block["previous_body"].split("\n") + [block["end"]]
        log("    回滚受管块到安装前的正文")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return True


def cmd_restore(args):
    path = os.path.join(BACKUP_ROOT, args.backup)
    manifest_path = os.path.join(path, "manifest.json")
    if not os.path.isfile(manifest_path):
        available = sorted(os.listdir(BACKUP_ROOT)) if os.path.isdir(BACKUP_ROOT) else []
        die("找不到备份 %s；现有备份：%s" % (manifest_path, available))
    manifest = json.loads(read_text(manifest_path))
    if manifest.get("version") != MANIFEST_VERSION:
        die("备份 %s 是 v%s 格式，本版 restore 只认 v%d（旧备份请手工比对）"
            % (args.backup, manifest.get("version", 1), MANIFEST_VERSION))
    entries = manifest["entries"]
    print("从 %s 还原 %d 条写入记录%s" % (path, len(entries),
                                        "（--dry-run，只预览）" if args.dry_run else ""))
    state = load_state()
    done = skipped = 0
    for entry in reversed(entries):  # 后写的先撤，顺序与 apply 相反
        target = entry["original_path"]
        kind, value = current_shape(target)
        print("  [%s] %s" % (entry.get("component") or "?", target))
        print("    记录：kind=%s 安装前%s / 当前=%s"
              % (entry["kind"], "存在" if entry["existed"] else "不存在", kind))
        # 受管块用块级判断：文件整体 sha 一变（用户在别处加了行）就跳过的话，
        # 「保留安装后新增内容」与「撤销受管块」这两件事会互相打架。
        block_scoped = entry["kind"] == "config_block" and entry["existed"]
        reason = None if block_scoped else restore_guard(entry)
        if reason and not args.force:
            print("    跳过：%s；确认要覆盖再加 --force" % reason)
            skipped += 1
            continue
        if args.dry_run:
            print("    将执行：%s" % restore_intent(entry))
            continue
        changed = apply_restore(entry, path, args.force)
        if changed:
            done += 1
            # 首装的撤销要销号；更新的回滚要把上一版记录放回去 ——
            # 一律销号的话，「装 v1 → 更新 v2 → 回滚」之后 v1 就成了「不是本入口装的」。
            before = entry.get("state_before") or {}
            if before:
                state.setdefault("components", {}).update(before)
                print("    安装记录回到上一版（%s）" % ", ".join(sorted(before)))
            elif entry.get("component"):
                state.get("components", {}).pop(entry["component"], None)
        else:
            skipped += 1
    if not args.dry_run:
        save_state(state)
        print("已还原 %d 条，跳过 %d 条；安装记录同步回滚（首装的销号，更新的回到上一版）" % (done, skipped))
        print("提示：还原后再跑一次 plan，确认结论回到「未安装」而不是「被改过」")
    return 0


def restore_intent(entry):
    if entry["kind"] == "config_block":
        return "只回滚受管块（块外内容不动）"
    if not entry["existed"]:
        return "删除 %s（安装前它不存在）" % entry["original_path"]
    if entry["kind"] == "symlink":
        return "把符号链接指回 %s" % entry["link_target"]
    return "用备份文件覆盖回去（sha256=%s）" % (entry["sha256"] or "?")[:12]


def apply_restore(entry, backup_dir, force):
    target = entry["original_path"]

    def log(text):
        print(text)

    if entry["kind"] == "config_block":
        if entry["existed"]:
            return restore_config_block(entry, target, force, log)
        if os.path.lexists(target):
            os.unlink(target)
            log("    删除文件（安装前它不存在）")
            return True
        return False
    if not entry["existed"]:
        if os.path.lexists(target):
            os.unlink(target)
            log("    已删除（安装前它不存在）")
        created = entry.get("created_dir")
        if created and os.path.isdir(created) and not os.listdir(created):
            os.rmdir(created)
            log("    连同本入口新建的空目录一起删除：%s" % created)
        return True
    if entry["kind"] == "symlink":
        if os.path.lexists(target):
            os.unlink(target)
        os.symlink(entry["link_target"], target)
        log("    符号链接已指回 %s" % entry["link_target"])
        return True
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    shutil.copy2(os.path.join(backup_dir, entry["backup_file"]), target)
    ok = sha256_file(target) == entry["sha256"]
    log("    已还原 sha256=%s %s" % (sha256_file(target)[:12], "✓" if ok else "✗ 不一致"))
    return True


def main(argv):
    parser = argparse.ArgumentParser(prog="env.py", description="个人开发环境的安装 / 更新 / 检查入口")
    subparsers = parser.add_subparsers(dest="verb")
    for verb in ("plan", "apply", "check"):
        sub = subparsers.add_parser(verb)
        sub.add_argument("--profile")
        sub.add_argument("--only", action="append", metavar="ID")
        if verb != "check":
            # check 不给 --force：它的职责是如实报漂移，不是把漂移说成没事。
            sub.add_argument("--force", action="store_true",
                             help="接管「不是本入口装的 / 安装后被改过」的目标（覆盖前照常备份）")
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--dry-run", action="store_true")
    restore.add_argument("--force", action="store_true",
                         help="安装后被改过的目标也照样回滚（默认跳过并报告）")
    args = parser.parse_args(argv)
    if not args.verb:
        parser.print_help()
        return 2
    if args.verb == "restore":
        return cmd_restore(args)
    return cmd_run(args, args.verb)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
