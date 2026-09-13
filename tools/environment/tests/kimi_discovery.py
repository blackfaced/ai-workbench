#!/usr/bin/env python3
"""Isolated ACP fixture tests; no real HOME, configuration or model calls."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time
import unittest

ENV_DIR = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(tempfile.mkdtemp(prefix="aiwb-kimi-fixtures-"))

SERVER = r'''#!/usr/bin/env python3
import json, os, signal, subprocess, sys, time
from pathlib import Path
root = Path(__file__).parent
mode = root.joinpath("mode").read_text()
root.joinpath("pid").write_text(str(os.getpid()))
if mode == "config":
    sys.exit(2)
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    root.joinpath("child-pid").write_text(str(child.pid))
def emit(value):
    print(json.dumps(value), flush=True)
for raw in sys.stdin:
    req = json.loads(raw)
    with root.joinpath("requests").open("a") as f:
        f.write(req["method"] + "\n")
    assert req["method"] in ("initialize", "session/new")
    if req["method"] == "initialize":
        if mode == "init-error":
            emit({"jsonrpc":"2.0", "id":1, "error":{"code":-32000,"message":"secret-error"}})
        else:
            emit({"jsonrpc":"2.0", "id":1, "result":{"protocolVersion":1}})
        continue
    assert req["params"]["mcpServers"] == []
    assert Path(req["params"]["cwd"]).is_absolute()
    if mode in ("silent", "child"):
        time.sleep(30)
        continue
    if mode == "partial":
        sys.stdout.write('{"jsonrpc":'); sys.stdout.flush(); time.sleep(30)
        continue
    if mode == "malformed":
        print("not json", flush=True); continue
    if mode == "new-error":
        emit({"jsonrpc":"2.0", "id":2, "error":{"code":-32602,"message":"secret-error"}}); continue
    result = {"jsonrpc":"2.0", "id":2, "result":{"sessionId":"fixture-session"}}
    commands = [{"name":"skill:demo-skill", "description":"fixture"},
                {"name":"skill:README", "description":"upstream index"}]
    if mode == "empty": commands = []
    if mode == "duplicate": commands += commands[:1]
    if mode == "bad-shape": commands = {}
    if mode == "bad-entry": commands = [{"name":"skill:demo-skill"}]
    update = {"jsonrpc":"2.0", "method":"session/update", "params":{
        "sessionId":"other" if mode == "wrong-session" else "fixture-session",
        "update":{"sessionUpdate":"available_commands_update", "availableCommands":commands}}}
    if mode == "before":
        # Notification and response in a single pipe write must both survive buffering.
        sys.stdout.write(json.dumps(update)+"\n"+json.dumps(result)+"\n");sys.stdout.flush()
    else:
        emit(result)
        if mode not in ("no-list", "early-eof"): emit(update)
    if mode == "early-eof": sys.exit(0)
'''

class KimiDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=ARTIFACTS))
        self.client = self.root / "kimi"
        self.client.write_text(SERVER)
        self.client.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), AIWB_DISCOVERY_TIMEOUT="0.8")

    def probe(self, mode):
        (self.root / "mode").write_text(mode)
        started = time.monotonic()
        p = subprocess.run([sys.executable, str(ENV_DIR / "kimi_skills_discovery.py"),
                            str(self.client)], env=self.env, capture_output=True, text=True, timeout=5)
        (self.root / (mode + ".result.json")).write_text(json.dumps({"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}))
        self.assertLess(time.monotonic()-started, 4)
        # Exit status is not enough: ensure the actual client PID was reaped.
        pid = self.root / "pid"
        self.assertTrue(pid.exists(), p.stderr)
        with self.assertRaises(ProcessLookupError): os.kill(int(pid.read_text()), 0)
        requests = self.root / "requests"
        if mode != "config": self.assertTrue(requests.exists(), p.stderr)
        if requests.exists():
            self.assertLessEqual(set(requests.read_text().splitlines()), {"initialize", "session/new"})
        return p

    def test_notifications_before_and_after_response(self):
        for mode in ("before", "after"):
            with self.subTest(mode=mode):
                p = self.probe(mode)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("demo-skill\tacp:skill:demo-skill", p.stdout)
                self.assertIn("README\tacp:skill:README", p.stdout)

    def test_failures_are_not_partial_success_or_secret_output(self):
        for mode in ("config", "init-error", "new-error", "malformed", "bad-shape", "bad-entry", "early-eof", "duplicate",
                     "no-list", "wrong-session", "partial", "silent"):
            with self.subTest(mode=mode):
                p = self.probe(mode)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stdout, "")
                self.assertNotIn("secret-error", p.stderr)
                self.assertTrue(p.stderr.strip())

    def test_empty_list_is_valid_discovery_but_not_profile_acceptance(self):
        p = self.probe("empty")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "")

    def test_timeout_reaps_descendant(self):
        p = self.probe("child")
        self.assertNotEqual(p.returncode, 0)
        pid = int((self.root / "child-pid").read_text())
        # Orphan zombies may briefly await init; they must not be executing.
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
        self.assertTrue(state.returncode == 1 or state.stdout.strip().startswith("Z"), state.stdout)

    def test_profile_check_requires_selected_skills_and_preserves_readme(self):
        from regression import Sandbox, DEMO_SKILL, base_profile
        box = Sandbox(str(self.root / "repo-test"))
        spec = {"discovery_cmd": "%s kimi_skills_discovery.py %s" % (sys.executable, self.client),
                "discovery_format":"commands", "require_profile_skills":True}
        box.profile(base_profile([DEMO_SKILL], {"kimi":spec,"shared":{"skills_dir":"~/.agents/skills"}}))
        self.assertEqual(box.run("apply", "--profile", "harness")[0], 0)
        readme = Path(box.path(".agents", "skills", "README.md"))
        readme.write_text("upstream index must survive\n")
        for mode, expected in [("after",0),("empty",1),("new-error",1)]:
            (self.root / "mode").write_text(mode)
            code, out = box.run("check", "--profile", "harness")
            (self.root / (mode+".env-check.txt")).write_text(out)
            self.assertEqual(code, expected, out)
            if mode == "empty": self.assertIn("缺少 Profile Skill", out)
            if mode == "new-error": self.assertIn("原生发现失败", out)
            if mode == "after": self.assertIn("额外原生命令 skill:README", out)
            self.assertEqual(readme.read_text(), "upstream index must survive\n")

if __name__ == "__main__":
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(KimiDiscoveryTest))
    if result.wasSuccessful():
        shutil.rmtree(ARTIFACTS)
    else:
        print("First failure evidence retained:", ARTIFACTS)
    sys.exit(0 if result.wasSuccessful() else 1)
