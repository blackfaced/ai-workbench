#!/usr/bin/env python3
"""Inline Skill packaging regressions; only disposable HOME/source copies."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from regression import ENV_DIR, Sandbox, DEMO_SKILL, FRONTMATTER, SKILL_BODY, base_profile

REPO = Path(ENV_DIR).parent.parent
spec = importlib.util.spec_from_file_location("inline_skill_env", Path(ENV_DIR) / "env.py")
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)
FULL = FRONTMATTER.rstrip("\n") + "\n\n" + SKILL_BODY


class InlineSkillTests(unittest.TestCase):
    def test_renderer_preserves_inline_bytes_and_legacy_output(self):
        self.assertEqual(env.render_skill(None, FULL), FULL)
        self.assertEqual(env.render_skill(FRONTMATTER, SKILL_BODY), FULL)

    def test_renderer_rejects_double_header_and_missing_inline_metadata(self):
        for header, body in ((FRONTMATTER, FULL), (None, SKILL_BODY),
                             (None, "---\nname: demo-skill\n"),
                             (None, "---\nname: demo-skill\n---\nBody\n"),
                             (None, "---\ndescription: Example\n---\nBody\n")):
            with self.subTest(header=header, body=body):
                with self.assertRaises(ValueError):
                    env.render_skill(header, body)

    def test_repository_entries_are_self_describing(self):
        entries = sorted((REPO / "skills").glob("*/SKILL.md"))
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(skill=entry.parent.name):
                data, error = env.parse_frontmatter(str(entry))
                self.assertIsNone(error)
                self.assertEqual(data["name"], entry.parent.name)
                self.assertTrue(data.get("description"))
                self.assertFalse((entry.parent / "clients/shared.frontmatter.md").exists())
                self.assertEqual(env.render_skill(None, entry.read_text()), entry.read_text())
        for path in sorted((REPO / "tools/environment/profiles").glob("*.json")):
            profile = json.loads(path.read_text())
            for comp in profile["components"]:
                if comp["type"] != "skill":
                    continue
                with self.subTest(profile=path.name, skill=comp["name"]):
                    data, error = env.parse_frontmatter(str(REPO / comp["body"]))
                    self.assertIsNone(error)
                    self.assertEqual(data["name"], comp["name"])
                    for client in comp["clients"].values():
                        self.assertNotIn("frontmatter", client)
                        for source in client.get("files", {}).values():
                            self.assertTrue((REPO / source).is_file(), source)

    def test_public_cli_migration_is_noop_then_upgrade_and_restore(self):
        with tempfile.TemporaryDirectory(prefix="aiwb-inline-migration-") as tmp:
            box = Sandbox(tmp)
            box.profile(base_profile([DEMO_SKILL]))
            rc, out = box.run("apply", "--profile", "harness")
            self.assertEqual(rc, 0, out)
            target = Path(box.path(".agents/skills/demo-skill/SKILL.md"))
            self.assertEqual(target.read_text(), FULL)
            state_before = box.state()
            backup_before = box.latest_backup()
            source = Path(box.repo) / DEMO_SKILL["body"]
            source.write_text(FULL, encoding="utf-8")
            (source.parent / "clients/shared.frontmatter.md").unlink()
            inline = copy.deepcopy(DEMO_SKILL)
            del inline["clients"]["shared"]["frontmatter"]
            box.profile(base_profile([inline]))
            for action in ("plan", "apply", "check"):
                rc, out = box.run(action, "--profile", "harness")
                self.assertEqual(rc, 0, out)
                self.assertEqual(target.read_text(), FULL)
                self.assertEqual(box.state(), state_before)
                self.assertEqual(box.latest_backup(), backup_before)
            source.write_text(FULL + "\nUpdated instructions.\n", encoding="utf-8")
            rc, out = box.run("apply", "--profile", "harness")
            self.assertEqual(rc, 0, out)
            self.assertEqual(target.read_text(), source.read_text())
            rc, out = box.run("restore", "--backup", box.latest_backup())
            self.assertEqual(rc, 0, out)
            self.assertEqual(target.read_text(), FULL)
            mine = FULL + "\nUser-owned amendment.\n"
            target.write_text(mine, encoding="utf-8")
            for action in ("apply", "check"):
                rc, out = box.run(action, "--profile", "harness")
                self.assertEqual(rc, 1, out)
                self.assertEqual(target.read_text(), mine)

    def test_fresh_inline_install_and_restore(self):
        with tempfile.TemporaryDirectory(prefix="aiwb-inline-fresh-") as tmp:
            box = Sandbox(tmp)
            inline = copy.deepcopy(DEMO_SKILL)
            del inline["clients"]["shared"]["frontmatter"]
            (Path(box.repo) / inline["body"]).write_text(FULL, encoding="utf-8")
            box.profile(base_profile([inline]))
            target = Path(box.path(".agents/skills/demo-skill/SKILL.md"))
            rc, out = box.run("plan", "--profile", "harness")
            self.assertEqual(rc, 0, out)
            self.assertFalse(target.exists())
            for action in ("apply", "check"):
                rc, out = box.run(action, "--profile", "harness")
                self.assertEqual(rc, 0, out)
            self.assertEqual(target.read_text(), FULL)
            rc, out = box.run("restore", "--backup", box.latest_backup())
            self.assertEqual(rc, 0, out)
            self.assertFalse(target.exists())
            self.assertFalse(box.state()["components"])

    def test_double_header_fails_before_installing(self):
        with tempfile.TemporaryDirectory(prefix="aiwb-inline-conflict-") as tmp:
            box = Sandbox(tmp)
            (Path(box.repo) / DEMO_SKILL["body"]).write_text(FULL, encoding="utf-8")
            box.profile(base_profile([DEMO_SKILL]))
            for action in ("plan", "apply", "check"):
                rc, out = box.run(action, "--profile", "harness")
                self.assertNotEqual(rc, 0, out)
                self.assertIn("frontmatter", out)
                self.assertFalse(Path(box.path(".agents/skills/demo-skill")).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
