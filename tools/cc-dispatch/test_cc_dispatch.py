#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cc_dispatch 的离线测试。

覆盖四类风险：

  1. 续跑跑错仓 —— 必须拒绝；
  2. 配置缺失或指向本机代理 —— 必须拒绝并说明原因；
  3. 凭据外泄 —— 错误信息不得包含 token；
  4. 参数缺失 —— 给出可读错误而不是静默执行。

只用标准库，兼容 Python 3.9；不联网、不启动真实 claude 进程。

    python3 tools/cc-dispatch/test_cc_dispatch.py
"""

import json
import os
import tempfile
import unittest
from unittest import mock

import cc_dispatch as cd

PLACEHOLDER_BASE = "https://gateway.example/api"


class TempHome:
    """在临时目录里造出 ~/.claude 的最小结构。"""

    def __init__(self, tmpdir):
        self.tmpdir = tmpdir
        self.projects = os.path.join(tmpdir, "projects")
        os.makedirs(self.projects, exist_ok=True)

    def write_config(self, base_url=PLACEHOLDER_BASE, token="tok-placeholder",
                     model="model-placeholder", name="cfg.json"):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            json.dump({"providers": {"default": {
                "base_url": base_url,
                "auth_token": token,
                "model": model,
            }}}, f)
        return path

    def write_transcript(self, session_id, cwd):
        slug = cwd.replace("/", "-")
        d = os.path.join(self.projects, slug)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, session_id + ".jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "attachment", "cwd": cwd}) + "\n")
            f.write(json.dumps({"type": "user",
                                "message": {"role": "user", "content": "hi"}}) + "\n")
        return path


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = TempHome(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class TestConfigLoading(ConfigTestCase):
    def test_reads_provider_triple(self):
        path = self.home.write_config()
        p = cd.resolve_provider(cd.load_config(path))
        self.assertEqual(p["base_url"], PLACEHOLDER_BASE)
        self.assertEqual(p["auth_token"], "tok-placeholder")
        self.assertEqual(p["model"], "model-placeholder")

    def test_missing_file_is_reported(self):
        with self.assertRaises(cd.DispatchError) as ctx:
            cd.load_config(os.path.join(self._td.name, "nope.json"))
        self.assertIn("不存在", str(ctx.exception))

    def test_invalid_json_is_reported(self):
        path = os.path.join(self._td.name, "bad.json")
        with open(path, "w") as f:
            f.write("{not json")
        with self.assertRaises(cd.DispatchError) as ctx:
            cd.load_config(path)
        self.assertIn("JSON", str(ctx.exception))

    def test_unknown_provider_lists_available(self):
        path = self.home.write_config()
        with self.assertRaises(cd.DispatchError) as ctx:
            cd.resolve_provider(cd.load_config(path), "missing")
        self.assertIn("default", str(ctx.exception))

    def test_loopback_base_url_is_rejected(self):
        """本机代理端口会随宿主进程失效，不能用于后台会话。"""
        for bad in ("http://127.0.0.1:8811", "http://localhost:5000",
                    "http://[::1]:9000"):
            path = self.home.write_config(base_url=bad)
            with self.assertRaises(cd.DispatchError) as ctx:
                cd.resolve_provider(cd.load_config(path))
            self.assertIn("本机端口", str(ctx.exception))

    def test_loopback_variants_rejected(self):
        """漏网写法也必须拦：0.0.0.0、host.docker.internal、无 scheme、127.x。"""
        for bad in ("http://0.0.0.0:8811", "http://host.docker.internal:8811",
                    "127.0.0.1:8811", "http://127.0.0.2:9000",
                    "HTTPS://LOCALHOST/api", "http://[::1]:9000"):
            path = self.home.write_config(base_url=bad)
            with self.assertRaises(cd.DispatchError, msg=bad):
                cd.resolve_provider(cd.load_config(path))

    def test_remote_host_still_allowed(self):
        path = self.home.write_config(base_url="https://gateway.example/api")
        p = cd.resolve_provider(cd.load_config(path))
        self.assertEqual(p["base_url"], "https://gateway.example/api")

    def test_missing_token_is_reported(self):
        path = self.home.write_config(token="")
        with self.assertRaises(cd.DispatchError) as ctx:
            cd.resolve_provider(cd.load_config(path))
        self.assertIn("auth_token", str(ctx.exception))

    def test_token_from_env(self):
        path = os.path.join(self._td.name, "envcfg.json")
        with open(path, "w") as f:
            json.dump({"providers": {"default": {
                "base_url": PLACEHOLDER_BASE,
                "auth_token_env": "CC_TEST_TOKEN",
            }}}, f)
        with mock.patch.dict(os.environ, {"CC_TEST_TOKEN": "from-env"}):
            p = cd.resolve_provider(cd.load_config(path))
        self.assertEqual(p["auth_token"], "from-env")

    def test_empty_env_token_is_reported(self):
        path = os.path.join(self._td.name, "envcfg2.json")
        with open(path, "w") as f:
            json.dump({"providers": {"default": {
                "base_url": PLACEHOLDER_BASE,
                "auth_token_env": "CC_TEST_ABSENT_TOKEN",
            }}}, f)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CC_TEST_ABSENT_TOKEN", None)
            with self.assertRaises(cd.DispatchError) as ctx:
                cd.resolve_provider(cd.load_config(path))
        self.assertIn("CC_TEST_ABSENT_TOKEN", str(ctx.exception))


class TestResumeGuard(ConfigTestCase):
    """续跑前必须核验 session 归属目录。"""

    def setUp(self):
        super().setUp()
        self.home.write_transcript("abc-123", "/work/repo-a")

    def test_same_dir_allowed(self):
        cd.assert_resume_dir("abc-123", "/work/repo-a",
                             projects_root=self.home.projects)

    def test_trailing_slash_normalised(self):
        cd.assert_resume_dir("abc-123", "/work/repo-a/",
                             projects_root=self.home.projects)

    def test_different_dir_rejected(self):
        with self.assertRaises(cd.DispatchError) as ctx:
            cd.assert_resume_dir("abc-123", "/work/repo-b",
                                 projects_root=self.home.projects)
        msg = str(ctx.exception)
        self.assertIn("repo-a", msg)
        self.assertIn("repo-b", msg)

    def test_unknown_session_rejected(self):
        with self.assertRaises(cd.DispatchError):
            cd.assert_resume_dir("ghost", "/work/repo-a",
                                 projects_root=self.home.projects)

    def test_resume_missing_directory_reported_clearly(self):
        """目录不存在时应说目录，而不是把 cwd 错误报成找不到二进制。"""
        args = mock.Mock(session_id="abc-123", directory="/definitely/not/here",
                         prompt="go", provider="default")
        with mock.patch.object(cd, "projects_root",
                               return_value=self.home.projects):
            with self.assertRaises(cd.DispatchError) as ctx:
                cd.cmd_resume(args)
        msg = str(ctx.exception)
        self.assertIn("目录不存在", msg)
        self.assertNotIn("无法执行", msg)

    def test_running_session_rejected_before_resume(self):
        args = mock.Mock(session_id="abc-123", directory="/work/repo-a",
                         prompt="go", provider="default")
        with mock.patch.object(cd, "projects_root",
                               return_value=self.home.projects), \
             mock.patch.object(cd.os.path, "isdir", return_value=True), \
             mock.patch.object(cd, "is_session_running", return_value=True):
            with self.assertRaises(cd.DispatchError) as ctx:
                cd.cmd_resume(args)
        self.assertIn("claude stop", str(ctx.exception))


class TestArgValidation(unittest.TestCase):
    def test_empty_dir_rejected(self):
        with self.assertRaises(cd.DispatchError):
            cd.validate_start_args("", "n", "p")

    def test_missing_dir_rejected(self):
        with self.assertRaises(cd.DispatchError):
            cd.validate_start_args("/definitely/not/here", "n", "p")

    def test_empty_name_rejected(self):
        with self.assertRaises(cd.DispatchError):
            cd.validate_start_args("/tmp", "", "p")

    def test_name_with_separator_rejected(self):
        with self.assertRaises(cd.DispatchError):
            cd.validate_start_args("/tmp", "a/b", "p")

    def test_empty_prompt_rejected(self):
        with self.assertRaises(cd.DispatchError):
            cd.validate_start_args("/tmp", "n", "   ")

    def test_valid_args_pass(self):
        cd.validate_start_args("/tmp", "worker-1", "do something")


class TestEnvStripping(unittest.TestCase):
    """daemon 会把污染变量传染给 worker，必须剥掉。"""

    def test_anthropic_and_messaging_vars_stripped(self):
        env = {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:55884",
            "ANTHROPIC_AUTH_TOKEN": "wrapper-token",
            "ANTHROPIC_MODEL": "some-model",
            "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/s.sock",
            "CLAUDE_CODE_MESSAGING_TOKEN": "t",
            "CLAUDE_CODE_LAUNCHED_BY_SESSION_IDS": "abc",
            "PATH": "/usr/bin",
            "HOME": "/home/x",
        }
        out = cd.clean_env(env)
        for k in cd.STRIP_ENV:
            self.assertNotIn(k, out)
        self.assertEqual(out["PATH"], "/usr/bin")
        self.assertEqual(out["HOME"], "/home/x")


class TestCredentialSafety(ConfigTestCase):
    def test_redact_masks_token(self):
        line = "failed with token tok-placeholder in header"
        self.assertNotIn("tok-placeholder", cd.redact(line, ["tok-placeholder"]))

    def test_config_errors_do_not_leak_token(self):
        path = self.home.write_config(base_url="http://127.0.0.1:1",
                                      token="super-secret-value")
        with self.assertRaises(cd.DispatchError) as ctx:
            cd.resolve_provider(cd.load_config(path))
        self.assertNotIn("super-secret-value", str(ctx.exception))


class TestCommandBuilding(unittest.TestCase):
    def test_start_uses_binary_and_bg(self):
        argv = cd.build_start_argv("/work/a", "w1", "do it", binary="/bin/claude")
        self.assertEqual(argv[0], "/bin/claude")
        self.assertIn("--bg", argv)
        self.assertEqual(argv[-2:], ["w1", "do it"])

    def test_resume_uses_print_mode(self):
        argv = cd.build_resume_argv("sid-1", "go", binary="/bin/claude")
        self.assertEqual(argv[:4], ["/bin/claude", "--resume", "sid-1", "-p"])
        self.assertEqual(argv[-1], "go")

    def test_start_defaults_to_dont_ask(self):
        """后台会话无终端确认，默认 dontAsk 才不会卡在权限弹窗。"""
        argv = cd.build_start_argv("/work/a", "w1", "do it", binary="/bin/claude")
        self.assertIn("--permission-mode", argv)
        i = argv.index("--permission-mode")
        self.assertEqual(argv[i + 1], "dontAsk")

    def test_resume_defaults_to_dont_ask(self):
        argv = cd.build_resume_argv("sid-1", "go", binary="/bin/claude")
        i = argv.index("--permission-mode")
        self.assertEqual(argv[i + 1], "dontAsk")

    def test_permission_mode_override(self):
        argv = cd.build_start_argv("/work/a", "w1", "do it", binary="/bin/claude",
                                   permission_mode="bypassPermissions")
        i = argv.index("--permission-mode")
        self.assertEqual(argv[i + 1], "bypassPermissions")

    def test_wrapper_names_recognised(self):
        self.assertTrue(cd.is_wrapper_path("/x/claude-wrapper"))
        self.assertTrue(cd.is_wrapper_path("/x/agent-acp"))
        self.assertFalse(cd.is_wrapper_path("/x/versions/2.0.0"))


if __name__ == "__main__":
    unittest.main()
