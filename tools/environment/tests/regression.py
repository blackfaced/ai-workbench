#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四个已知缺陷的回归用例：全部在临时 HOME 与临时仓库副本里跑，不碰真机配置。

    python3 tools/environment/tests/regression.py

每个用例对应一条 2026-09-07 审查里被点名的问题：

    1  更新 Skill 会覆盖用户修改                       → 写入前先证明归属与摘要
    2  restore 丢失安装后新增的配置 / 首装撤不干净      → manifest v2 + 块级回滚
    3  重新引入重复 Skill，检查器却报告通过             → 按客户端可发现全集判重名
    4  缺工具、版本过低时只报告，不安装 / 不更新        → install_cmd / update_cmd

只用标准库，兼容 Python 3.9。任何一条不通过就以非 0 退出。
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_DIR = os.path.dirname(HERE)

BASHRC_BEFORE = """# 沙盒 ~/.bashrc
export SANDBOX_MARK=1

case $- in
  *i*) ;;
    *) return;;
esac

alias ll='ls -l'
"""

SKILL_BODY = "沙盒用的 Skill 正文，只为验证写入与回滚。\n"
FRONTMATTER = ("---\nname: demo-skill\ndescription: 回归用例专用，不会被安装到真机。\n"
               "author: 韩成\ndisable-model-invocation: true\n---\n")

FAILS = []
PASSES = []


def check(name, ok, detail=""):
    (PASSES if ok else FAILS).append(name)
    print("  %s %s%s" % ("✓" if ok else "✗", name, ("　— " + detail) if detail else ""))


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class Sandbox(object):
    """一份可丢弃的仓库副本 + 一个可丢弃的 HOME。"""

    def __init__(self, root):
        self.root = root
        self.home = os.path.join(root, "home")
        self.repo = os.path.join(root, "repo")
        self.env_dir = os.path.join(self.repo, "tools", "environment")
        os.makedirs(os.path.join(self.env_dir, "profiles"))
        for name in ("env.py", "skills_discovery.py", "kimi_skills_discovery.py"):
            shutil.copy2(os.path.join(ENV_DIR, name), os.path.join(self.env_dir, name))
        skill_dir = os.path.join(self.repo, "skills", "demo-skill")
        os.makedirs(os.path.join(skill_dir, "clients"))
        write(os.path.join(skill_dir, "SKILL.md"), SKILL_BODY)
        write(os.path.join(skill_dir, "clients", "shared.frontmatter.md"), FRONTMATTER)
        for sub in (".agents/skills", ".claude/skills", ".trae/skills", "bin"):
            os.makedirs(os.path.join(self.home, sub))
        write(os.path.join(self.home, ".bashrc"), BASHRC_BEFORE)
        # 让 bash -lc 能看到沙盒 bin，工具用例才有地方装假二进制
        write(os.path.join(self.home, ".bash_profile"),
              'export PATH="$HOME/bin:$PATH"\n[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"\n')

    def profile(self, data):
        write(os.path.join(self.env_dir, "profiles", "harness.json"),
              json.dumps(data, ensure_ascii=False, indent=2))

    def run(self, *argv):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["PATH"] = os.path.join(self.home, "bin") + os.pathsep + env["PATH"]
        proc = subprocess.Popen(
            [sys.executable, os.path.join(self.env_dir, "env.py")] + list(argv),
            cwd=self.repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        out, _ = proc.communicate(timeout=600)
        return proc.returncode, out

    def path(self, *parts):
        return os.path.join(self.home, *parts)

    def state(self):
        target = self.path(".ai-workbench", "environment", "state.json")
        return json.loads(read(target)) if os.path.isfile(target) else {"components": {}}

    def latest_backup(self):
        root = self.path(".ai-workbench", "environment", "backups")
        return sorted(os.listdir(root))[-1]


def base_profile(components, clients=None):
    return {
        "profile": "harness",
        "os": "Any",
        "shell": "/bin/bash",
        "why": "回归用例",
        "clients": clients or {"shared": {"skills_dir": "~/.agents/skills"}},
        "components": components,
    }


DEMO_SKILL = {
    "id": "demo-skill",
    "type": "skill",
    "name": "demo-skill",
    "body": "skills/demo-skill/SKILL.md",
    "source": "repo:skills/demo-skill",
    "revision": "in-repo",
    "clients": {
        "shared": {
            "dir": "~/.agents/skills",
            "frontmatter": "skills/demo-skill/clients/shared.frontmatter.md",
            "link_from": "~/.claude/skills",
        }
    },
}

DEMO_BLOCK = {
    "id": "demo-block",
    "type": "config_block",
    "path": "~/.bashrc",
    "comment_prefix": "#",
    "insert_before_re": "^case \\$- in",
    "why": "回归用例：验证块级回滚",
    "body": ["export DEMO_MANAGED=1"],
}


# --------------------------------------------------------------------------
# 用例 1：更新 Skill 不许覆盖用户修改
# --------------------------------------------------------------------------

def case_skill_overwrite(root):
    print("\n[用例 1] Skill 写入前的归属 / 摘要校验")
    box = Sandbox(os.path.join(root, "one"))
    box.profile(base_profile([DEMO_SKILL]))
    rc, _out = box.run("apply", "--profile", "harness")
    target = box.path(".agents", "skills", "demo-skill", "SKILL.md")
    check("首次 apply 成功且落盘", rc == 0 and os.path.isfile(target))
    check("符号链接建好", os.path.realpath(box.path(".claude", "skills", "demo-skill"))
          == os.path.realpath(box.path(".agents", "skills", "demo-skill")))

    mine = read(target) + "\n用户自己加的一行，不许被吃掉。\n"
    write(target, mine)
    rc, out = box.run("plan", "--profile", "harness")
    check("用户改过之后 plan 判为需人处理", "与安装记录不一致" in out)
    rc, out = box.run("apply", "--profile", "harness")
    check("apply 不覆盖用户修改", read(target) == mine)
    check("apply 以 rc=1 报出该冲突", rc == 1)

    # 目标存在但不是本入口装的
    box2 = Sandbox(os.path.join(root, "two"))
    box2.profile(base_profile([DEMO_SKILL]))
    foreign = box2.path(".agents", "skills", "demo-skill", "SKILL.md")
    os.makedirs(os.path.dirname(foreign))
    write(foreign, "别人的 Skill，跟本入口无关。\n")
    rc, out = box2.run("apply", "--profile", "harness")
    check("陌生同名文件不被接管", read(foreign) == "别人的 Skill，跟本入口无关。\n")
    check("并给出「不是本入口装的」结论", "不是本入口装的" in out)


# --------------------------------------------------------------------------
# 用例 2：restore 的三类操作与安装后改动保护
# --------------------------------------------------------------------------

def case_restore(root):
    print("\n[用例 2] restore：块级回滚 / 首装完整撤销 / 安装后改动保护")
    box = Sandbox(os.path.join(root, "one"))
    box.profile(base_profile([DEMO_BLOCK, DEMO_SKILL]))
    rc, _out = box.run("apply", "--profile", "harness")
    check("apply 成功", rc == 0)
    backup = box.latest_backup()

    # 安装之后用户又往同一个文件里加了自己的东西
    bashrc = box.path(".bashrc")
    write(bashrc, read(bashrc) + "\nexport USER_ADDED_AFTER_INSTALL=1\n")

    rc, out = box.run("restore", "--backup", backup, "--dry-run")
    check("dry-run 不动文件", "USER_ADDED_AFTER_INSTALL" in read(bashrc) and rc == 0)

    rc, out = box.run("restore", "--backup", backup)
    text = read(bashrc)
    check("受管块已撤掉", "DEMO_MANAGED" not in text)
    check("安装后新增的用户配置还在", "USER_ADDED_AFTER_INSTALL=1" in text)
    check("块外原有内容一字未动", "alias ll='ls -l'" in text and "SANDBOX_MARK=1" in text)
    check("插入块时带的空行也撤干净了", "\n\n\ncase $- in" not in text)
    check("首装的 Skill 文件被删除",
          not os.path.exists(box.path(".agents", "skills", "demo-skill", "SKILL.md")))
    check("本入口新建的 Skill 目录被删除",
          not os.path.exists(box.path(".agents", "skills", "demo-skill")))
    check("首装的符号链接被删除", not os.path.lexists(box.path(".claude", "skills", "demo-skill")))
    check("安装记录已清空", box.state().get("components") == {})
    rc, out = box.run("plan", "--profile", "harness")
    check("撤销后 plan 回到「待安装」而不是「被改过」",
          "待安装" in out and "不是本入口装的" not in out)

    # 安装后被改过的目标：默认跳过，--force 才回滚
    box2 = Sandbox(os.path.join(root, "two"))
    box2.profile(base_profile([DEMO_BLOCK]))
    box2.run("apply", "--profile", "harness")
    backup2 = box2.latest_backup()
    target = box2.path(".bashrc")
    write(target, read(target).replace("export DEMO_MANAGED=1", "export DEMO_MANAGED=0"))
    rc, out = box2.run("restore", "--backup", backup2)
    check("块被改过时默认跳过", "DEMO_MANAGED=0" in read(target) and "跳过" in out)
    rc, out = box2.run("restore", "--backup", backup2, "--force")
    check("--force 才真的回滚", "DEMO_MANAGED" not in read(target))


# --------------------------------------------------------------------------
# 用例 3：重复 Skill 必须被检查出来
# --------------------------------------------------------------------------

def case_duplicates(root):
    print("\n[用例 3] 按客户端可发现全集判重名")
    box = Sandbox(os.path.join(root, "one"))
    clients = {
        "shared": {"skills_dir": "~/.agents/skills"},
        "fakecli": {"skills_dir": "~/.trae/skills",
                    "discovery_dirs": ["~/.trae/skills", "~/.agents/skills"]},
    }
    box.profile(base_profile([DEMO_SKILL], clients))
    box.run("apply", "--profile", "harness")
    rc, out = box.run("check", "--profile", "harness")
    check("单副本时检查通过", rc == 0 and "重名 0 项" in out)

    # 人为在另一个客户端目录里再放一份（正是之前 Mac 上的形态）
    dup = box.path(".trae", "skills", "demo-skill")
    os.makedirs(dup)
    write(os.path.join(dup, "SKILL.md"), FRONTMATTER + "\n另一份副本。\n")
    rc, out = box.run("check", "--profile", "harness")
    check("聚合发现下重名被判出", "重名 ✗ demo-skill" in out)
    check("check 因此以 rc=1 收尾", rc == 1)

    # 同一目标的符号链接别名不算重复
    shutil.rmtree(dup)
    os.symlink(box.path(".agents", "skills", "demo-skill"), dup)
    rc, out = box.run("check", "--profile", "harness")
    check("符号链接别名不误判为重复", rc == 0 and "同一目标的别名" in out)

    # 原生发现接口失败时必须报错，不能静悄悄当通过
    clients["fakecli"] = {"skills_dir": "~/.trae/skills", "discovery_cmd": "exit 7"}
    box.profile(base_profile([DEMO_SKILL], clients))
    rc, out = box.run("check", "--profile", "harness")
    check("原生发现失败不被当作通过", rc == 1 and "无法确认可发现集合" in out)


# --------------------------------------------------------------------------
# 用例 4：缺工具要装，版本低要更新
# --------------------------------------------------------------------------

def tool_component(**extra):
    comp = {
        "id": "demotool",
        "type": "tool",
        "bin": "demotool",
        "owner": "harness",
        "required": True,
        "version_cmd": "demotool --version",
        "version_re": "demotool ([0-9]+\\.[0-9]+\\.[0-9]+)",
        "identity_re": "^demotool ",
    }
    comp.update(extra)
    return comp


def fake_tool_cmd(version):
    """一条把假二进制写进沙盒 bin 的命令，冒充某个软件的安装器。"""
    return ('mkdir -p "$HOME/bin" && printf \'#!/bin/sh\\necho "demotool %s"\\n\' '
            '> "$HOME/bin/demotool" && chmod +x "$HOME/bin/demotool"' % version)


def case_tools(root):
    print("\n[用例 4] 工具缺失要装、版本低要更新")
    box = Sandbox(os.path.join(root, "one"))
    box.profile(base_profile([tool_component(install_cmd=fake_tool_cmd("1.0.0"))]))
    rc, out = box.run("plan", "--profile", "harness")
    check("缺失且有渠道时进入待改动", "安装 demotool" in out)
    rc, out = box.run("apply", "--profile", "harness")
    check("apply 真的装上了", rc == 0 and os.path.isfile(box.path("bin", "demotool")))
    rc, out = box.run("check", "--profile", "harness")
    check("装完 check 通过", rc == 0)

    # 版本低于底线 → 更新
    box.profile(base_profile([tool_component(min_version="2.0.0",
                                             update_cmd=fake_tool_cmd("2.3.4"))]))
    rc, out = box.run("plan", "--profile", "harness")
    check("版本落后进入待改动而不是只报告", "更新 demotool" in out)
    rc, out = box.run("apply", "--profile", "harness")
    check("apply 后版本达标", rc == 0)
    rc, out = box.run("check", "--profile", "harness")
    check("更新后 check 通过", rc == 0)

    # 更新渠道无效（跑完版本还是低）→ 必须失败，不许假装成功
    box.profile(base_profile([tool_component(min_version="9.9.9",
                                             update_cmd=fake_tool_cmd("2.3.4"))]))
    rc, out = box.run("apply", "--profile", "harness")
    check("无效渠道被当场揭穿", rc == 1 and "这个渠道无效" in out)

    # 必需工具缺失且无渠道 → 需人处理
    box2 = Sandbox(os.path.join(root, "two"))
    box2.profile(base_profile([tool_component()]))
    rc, out = box2.run("check", "--profile", "harness")
    check("缺失且无渠道时判为需人处理", rc == 1 and "未登记已验证的安装渠道" in out)

    # 由安装器组件负责的工具：本次计划包含它就不算漏，不包含就要如实报出
    installer = {"id": "fake-installer", "type": "installer", "owner": "harness",
                 "check_cmd": "test -x \"$HOME/bin/demotool\"",
                 "apply_cmd": fake_tool_cmd("3.0.0")}
    box3 = Sandbox(os.path.join(root, "three"))
    box3.profile(base_profile([installer, tool_component(install_via="fake-installer")]))
    rc, out = box3.run("plan", "--profile", "harness")
    check("有安装器兜底时不误判为无渠道", "由它负责装" in out)
    rc, out = box3.run("apply", "--profile", "harness")
    check("安装器把工具装上了", os.path.isfile(box3.path("bin", "demotool")))
    box4 = Sandbox(os.path.join(root, "four"))
    box4.profile(base_profile([installer, tool_component(install_via="fake-installer")]))
    rc, out = box4.run("plan", "--profile", "harness", "--only", "demotool")
    check("--only 把安装器挡在外面时如实报出", "没有包含该组件" in out)



# --------------------------------------------------------------------------
# 用例 5：历史副本清理不许丢东西，--force 是唯一的接管入口
# --------------------------------------------------------------------------

def skill_with_stale(stale, files=None):
    comp = json.loads(json.dumps(DEMO_SKILL))
    comp["stale_copies"] = stale
    if files:
        comp["clients"]["shared"]["files"] = files
    return comp


def case_stale_and_force(root):
    print("\n[用例 5] 历史副本清理与 --force 接管")

    # 5a 历史副本是指向受管副本的符号链接：删链接，绝不能顺着它删到真身
    box = Sandbox(os.path.join(root, "one"))
    box.profile(base_profile([skill_with_stale(["~/.trae/skills/demo-skill"])]))
    box.run("apply", "--profile", "harness")
    real = box.path(".agents", "skills", "demo-skill", "SKILL.md")
    link = box.path(".trae", "skills", "demo-skill")
    os.symlink(box.path(".agents", "skills", "demo-skill"), link)
    rc, out = box.run("plan", "--profile", "harness")
    check("符号链接形态的历史副本按链接处理", "是符号链接" in out)
    rc, out = box.run("apply", "--profile", "harness")
    check("链接被删掉", not os.path.lexists(link))
    check("链接指向的真身毫发无伤", os.path.isfile(real))

    # 5b 历史副本里有受管副本没有的文件：不许删，交给人
    box2 = Sandbox(os.path.join(root, "two"))
    box2.profile(base_profile([skill_with_stale(["~/.codex/skills/demo-skill"])]))
    box2.run("apply", "--profile", "harness")
    stale = box2.path(".codex", "skills", "demo-skill")
    os.makedirs(os.path.join(stale, "agents"))
    shutil.copy2(real.replace(box.home, box2.home), os.path.join(stale, "SKILL.md"))
    write(os.path.join(stale, "agents", "openai.yaml"), "policy:\n  allow_implicit_invocation: false\n")
    rc, out = box2.run("apply", "--profile", "harness")
    check("有对不上的文件时整条 block", rc == 1 and "删了会丢东西" in out)
    check("该文件确实没被删", os.path.isfile(os.path.join(stale, "agents", "openai.yaml")))

    # 5b-1 换个形态：历史副本正是本入口上一版自己写下的（旧 Profile 每客户端各一份）。
    # 内容与新版正文对不上，但安装记录能证明它是我的 —— 这种不该卡人。
    box5 = Sandbox(os.path.join(root, "five"))
    old_profile = json.loads(json.dumps(DEMO_SKILL))
    old_profile["clients"] = {"fakecli": {
        "dir": "~/.trae/skills",
        "frontmatter": "skills/demo-skill/clients/shared.frontmatter.md"}}
    box5.profile(base_profile([old_profile]))
    box5.run("apply", "--profile", "harness")
    legacy = box5.path(".trae", "skills", "demo-skill", "SKILL.md")
    check("旧 Profile 先把副本装进客户端目录", os.path.isfile(legacy))
    write(os.path.join(box5.repo, "skills", "demo-skill", "SKILL.md"), SKILL_BODY + "新版多了一行。\n")
    box5.profile(base_profile([skill_with_stale(["~/.trae/skills/demo-skill"])]))
    rc, out = box5.run("apply", "--profile", "harness")
    check("安装记录能证明归属时无需 --force", rc == 0 and not os.path.exists(os.path.dirname(legacy)))
    check("旧组件记录一并销号", "demo-skill:fakecli" not in json.dumps(box5.state()))

    # 5b-2 --force 是这里唯一的松绑方式，且仍然逐个文件备份
    rc, out = box2.run("plan", "--profile", "harness", "--force")
    check("--force 下历史副本进入待改动", "--force 删除历史副本" in out)

    # 5c 把这个附带文件纳入受管副本之后，历史副本就能安全删除
    write(os.path.join(box2.repo, "skills", "demo-skill", "clients", "openai.yaml"),
          "policy:\n  allow_implicit_invocation: false\n")
    box2.profile(base_profile([skill_with_stale(
        ["~/.codex/skills/demo-skill"],
        {"agents/openai.yaml": "skills/demo-skill/clients/openai.yaml"})]))
    rc, out = box2.run("apply", "--profile", "harness")
    managed_yaml = box2.path(".agents", "skills", "demo-skill", "agents", "openai.yaml")
    check("附带文件被装进受管副本", os.path.isfile(managed_yaml))
    check("历史副本随之删除", rc == 0 and not os.path.exists(stale))
    backup = box2.latest_backup()
    rc, out = box2.run("restore", "--backup", backup)
    check("restore 能把删掉的历史副本原样放回",
          os.path.isfile(os.path.join(stale, "agents", "openai.yaml")))
    check("同一次 restore 也撤掉了刚装的附带文件", not os.path.exists(managed_yaml))

    # 5d 陌生同名文件：默认不动，--force 才接管，且接管后能撤回
    box3 = Sandbox(os.path.join(root, "three"))
    box3.profile(base_profile([DEMO_SKILL]))
    foreign = box3.path(".agents", "skills", "demo-skill", "SKILL.md")
    os.makedirs(os.path.dirname(foreign))
    write(foreign, "装机之前就在这儿的东西。\n")
    rc, out = box3.run("apply", "--profile", "harness")
    check("默认仍然不接管", rc == 1 and read(foreign) == "装机之前就在这儿的东西。\n")
    rc, out = box3.run("apply", "--profile", "harness", "--force")
    check("--force 接管并留下审计说明", rc == 0 and "--force 接管" in out)
    check("接管后内容换成受管形态", "回归用例专用" in read(foreign))
    rc, out = box3.run("restore", "--backup", box3.latest_backup())
    check("接管前的原文件能一字不差地还原", read(foreign) == "装机之前就在这儿的东西。\n")



# --------------------------------------------------------------------------
# 用例 6：2026-09-07 第二轮审查复现的四条
# --------------------------------------------------------------------------

def case_symlink_adoption(root):
    print("\n[用例 6a] 接管符号链接：不许顺着它改写别人的文件")
    box = Sandbox(os.path.join(root, "one"))
    box.profile(base_profile([DEMO_SKILL]))
    victim = box.path("victim.md")
    write(victim, "别人的文件，一个字都不该被动。\n")
    target = box.path(".agents", "skills", "demo-skill", "SKILL.md")
    os.makedirs(os.path.dirname(target))
    os.symlink(victim, target)

    rc, out = box.run("apply", "--profile", "harness")
    check("默认不接管符号链接目标", rc == 1 and "是符号链接" in out)
    check("被指向的文件没被动", read(victim) == "别人的文件，一个字都不该被动。\n")

    rc, out = box.run("apply", "--profile", "harness", "--force")
    check("--force 后换掉的是链接本身", rc == 0 and not os.path.islink(target))
    check("受管内容落在原路径上", "回归用例专用" in read(target))
    check("链接指向的文件依然一字未改", read(victim) == "别人的文件，一个字都不该被动。\n")

    rc, out = box.run("restore", "--backup", box.latest_backup())
    check("restore 把符号链接接回去", os.path.islink(target) and os.readlink(target) == victim)
    check("原内容因此完好可达", read(target) == "别人的文件，一个字都不该被动。\n")


def case_update_rollback_keeps_record(root):
    print("\n[用例 6b] 更新的回滚要恢复上一版记录，而不是一律销号")
    box = Sandbox(os.path.join(root, "two"))
    box.profile(base_profile([DEMO_SKILL, DEMO_BLOCK]))
    box.run("apply", "--profile", "harness")
    first = box.latest_backup()

    # 第二版：Skill 正文与受管块同时改
    write(os.path.join(box.repo, "skills", "demo-skill", "SKILL.md"), SKILL_BODY + "第二版。\n")
    second_block = json.loads(json.dumps(DEMO_BLOCK))
    second_block["body"] = ["export DEMO_MANAGED=2"]
    box.profile(base_profile([DEMO_SKILL, second_block]))
    rc, out = box.run("apply", "--profile", "harness")
    check("第二版装得上", rc == 0)
    second = box.latest_backup()
    check("确实产生了新的备份", second != first)

    rc, out = box.run("restore", "--backup", second)
    check("回滚打印出「回到上一版」", "安装记录回到上一版" in out)
    skill = box.path(".agents", "skills", "demo-skill", "SKILL.md")
    check("Skill 正文回到第一版", "第二版" not in read(skill))
    check("受管块回到第一版", "export DEMO_MANAGED=1" in read(box.path(".bashrc")))

    # 关键：此时再更新到第二版，必须仍然认得出「这是我装的」
    rc, out = box.run("apply", "--profile", "harness")
    check("再次更新不再误判为「不是本入口装的」",
          rc == 0 and "不是本入口装的" not in out)
    check("第二版内容重新写上", "第二版" in read(skill))
    check("受管块也回到第二版", "export DEMO_MANAGED=2" in read(box.path(".bashrc")))


FAKE_SERVER = r'''#!/usr/bin/env python3
import json, sys, time
mode = sys.argv[1]
delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
for raw in sys.stdin:
    try:
        msg = json.loads(raw)
    except ValueError:
        continue
    if msg.get("id") != 2:
        continue
    time.sleep(delay)
    if mode == "silent":
        time.sleep(30)
        break
    group = {"cwd": "/tmp", "skills": [{"name": "demo-skill", "path": "/tmp/demo-skill/SKILL.md"}],
             "errors": [] if mode == "clean" else [{"path": "/tmp/broken/SKILL.md",
                                                    "message": "frontmatter 解析失败"}]}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"data": [group]}}) + "\n")
    sys.stdout.flush()
    break
'''


def fake_client(root, name, mode, delay=0.0):
    """造一个假的 app-server：<name> app-server 会被 skills_discovery.py 起起来。"""
    server = os.path.join(root, "fake_server.py")
    if not os.path.isfile(server):
        write(server, FAKE_SERVER)
    path = os.path.join(root, name)
    write(path, '#!/bin/sh\nexec python3 "%s" %s %s\n' % (server, mode, delay))
    os.chmod(path, 0o755)
    return path


def case_discovery_errors_and_timeout(root):
    print("\n[用例 6c] 原生发现：清单里的解析错误要传出来，超时要真的超时")
    os.makedirs(root, exist_ok=True)
    discovery = os.path.join(ENV_DIR, "skills_discovery.py")
    env = dict(os.environ, PATH="%s:%s" % (root, os.environ["PATH"]))

    fake_client(root, "cleancli", "clean")
    proc = subprocess.run([sys.executable, discovery, "cleancli"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check("干净响应正常输出清单",
          proc.returncode == 0 and b"demo-skill\t" in proc.stdout)

    fake_client(root, "brokencli", "broken")
    proc = subprocess.run([sys.executable, discovery, "brokencli"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check("响应成功但带解析错误时判失败", proc.returncode == 6)
    check("并把错误原文报出来", "frontmatter 解析失败" in proc.stderr.decode("utf-8", "replace"))
    check("不吐出半张清单冒充结果", proc.stdout == b"")

    fake_client(root, "slowcli", "clean", delay=3.0)
    env_fast = dict(env, AIWB_DISCOVERY_TIMEOUT="0.5")
    started = time.time()
    proc = subprocess.run([sys.executable, discovery, "slowcli"], env=env_fast,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.time() - started
    check("0.5s 超时真的在 0.5s 附近返回（实测 %.1fs）" % elapsed,
          proc.returncode == 4 and elapsed < 2.0)

    fake_client(root, "silentcli", "silent")
    started = time.time()
    proc = subprocess.run([sys.executable, discovery, "silentcli"], env=env_fast,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.time() - started
    check("一直不出声也不会挂死（实测 %.1fs）" % elapsed,
          proc.returncode == 4 and elapsed < 2.0)

    leftover = subprocess.run(["pgrep", "-f", os.path.join(root, "fake_server.py")],
                              stdout=subprocess.PIPE)
    check("子进程被收干净，没留下孤儿", leftover.stdout.strip() == b"")


def case_profile_selection(root):
    print("\n[用例 7] 家用与工作 Mac：无法判定时不默认写工作机配置")
    os.makedirs(root)
    for name, system, hosts in [
        ("work-mac", "Darwin", {}),
        ("home-mac", "Darwin", {}),
        ("work-linux", "Linux", {"dev": {"match_hostname": "dev-test"}}),
    ]:
        write(os.path.join(root, name + ".json"), json.dumps({
            "os": system, "shell": "/bin/sh", "hosts": hosts, "components": []
        }))
    module_path = os.path.join(root, "env.py")
    shutil.copy2(os.path.join(ENV_DIR, "env.py"), module_path)
    spec = importlib.util.spec_from_file_location("profile_test_env", module_path)
    env = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(env)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        check("备份目录 UTC 格式在新 Python 上无弃用警告",
              bool(re.fullmatch(r"\d{8}T\d{6}Z", env.utc_stamp())))
        check("状态时间 UTC 格式保持兼容",
              bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", env.utc_iso())))
        check("Unix epoch 0 不被误当成当前时间", env.utc_iso(0) == "1970-01-01T00:00:00Z")

    def run(system, host, *args):
        output = io.StringIO()
        with mock.patch.object(env, "PROFILE_DIR", root), \
             mock.patch.object(env, "STATE_PATH", os.path.join(root, "state.json")), \
             mock.patch.object(env.platform, "system", return_value=system), \
             mock.patch.object(env.socket, "gethostname", return_value=host), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                code = env.main(["plan"] + list(args))
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue()

    code, out = run("Darwin", "home-test")
    check("多个 Mac Profile 要求显式选择", code != 0 and "显式 --profile" in out)
    code, out = run("Darwin", "home-test", "--profile", "home-mac")
    check("显式 home-mac 使用家用配置", code == 0 and "profile=home-mac" in out)
    code, out = run("Linux", "dev-test.local")
    check("已登记 Linux 主机仍自动匹配", code == 0 and "profile=work-linux" in out)
    code, out = run("Linux", "unknown-host")
    check("未知 Linux 主机不猜配置", code != 0 and "显式 --profile" in out)
    code, out = run("Darwin", "dev-test")
    check("跨操作系统的主机名不选错 Profile", code != 0 and "显式 --profile" in out)
    os.unlink(os.path.join(root, "home-mac.json"))
    code, out = run("Darwin", "one-mac")
    check("只有一个 Mac Profile 时兼容自动选择", code == 0 and "profile=work-mac" in out)


def main():
    root = tempfile.mkdtemp(prefix="aiwb-env-regression-")
    print("沙盒根目录：%s" % root)
    case_skill_overwrite(os.path.join(root, "c1"))
    case_restore(os.path.join(root, "c2"))
    case_duplicates(os.path.join(root, "c3"))
    case_tools(os.path.join(root, "c4"))
    case_stale_and_force(os.path.join(root, "c5"))
    case_symlink_adoption(os.path.join(root, "c6"))
    case_update_rollback_keeps_record(os.path.join(root, "c6"))
    case_discovery_errors_and_timeout(os.path.join(root, "c6", "cli"))
    case_profile_selection(os.path.join(root, "c7"))
    kimi = subprocess.run([sys.executable, os.path.join(HERE, "kimi_discovery.py")],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    write(os.path.join(root, "kimi-discovery.log"), kimi.stdout)
    check("Kimi ACP 隔离协议与 Profile 缺项回归", kimi.returncode == 0, kimi.stdout if kimi.returncode else "")
    print("\n通过 %d 项，失败 %d 项" % (len(PASSES), len(FAILS)))
    if FAILS:
        for name in FAILS:
            print("  失败：%s" % name)
        print("沙盒保留在 %s，自己进去看" % root)
        return 1
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
