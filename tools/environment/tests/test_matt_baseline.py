#!/usr/bin/env python3
"""Real filesystem/Git-oracle checks; no manager, network or client invocation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills/setup-aiwb/scripts/verify_matt_baseline.py"
spec = importlib.util.spec_from_file_location("verify_matt_baseline", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class StandaloneBaseline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aiwb-standalone-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = patch.dict(os.environ, {"HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.project = self.root / "project"
        self.project.mkdir()
        self.git(self.project, "init", "-q")
        # Git, not the verifier's hashing code, supplies the independent oracle.
        source = self.root / "source"
        source.mkdir()
        self.git(source, "init", "-q")
        self.vendor = source / "package"
        self.vendor.mkdir()
        (self.vendor / "SKILL.md").write_text("---\nname: fixture\ndisable-model-invocation: true\n---\n")
        (self.vendor / "domain.md").write_text("Fixture domain\n")
        (self.vendor / "agents").mkdir()
        (self.vendor / "agents/openai.yaml").write_text("interface: {}\n")
        (self.vendor / "agents.txt").write_text("Git directory/file sort control\n")
        self.git(source, "add", "package")
        tree = self.git(source, "write-tree")
        expected = self.git(source, "rev-parse", tree + ":package")
        self.oracle = patch.dict(verifier.SOURCE, {"tree": expected})
        self.oracle.start()
        self.addCleanup(self.oracle.stop)
        self.entry = self.project / verifier.ENTRY
        self.entry.parent.mkdir(parents=True)

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    def copied(self):
        shutil.copytree(self.vendor, self.entry)

    def test_direct_copy_without_registry_passes_read_only(self):
        self.copied()
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.entry.rglob("*") if p.is_file()}
        self.assertEqual(verifier.verify(self.project)["status"], "PASS")
        self.assertEqual(verifier.verify(self.project)["status"], "PASS")
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.entry.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), [])

    def test_vendor_symlink_without_registry_passes(self):
        self.entry.symlink_to(self.vendor, target_is_directory=True)
        self.assertEqual(verifier.verify(self.project)["status"], "PASS")

    def test_global_only_never_falls_back(self):
        global_copy = self.home / verifier.ENTRY
        global_copy.parent.mkdir(parents=True)
        shutil.copytree(self.vendor, global_copy)
        self.assertEqual(verifier.verify(self.project)["code"], "PROJECT_DEPENDENCY_MISSING")
        self.assertFalse(self.entry.exists())

    def test_equal_global_copy_cannot_be_project_target(self):
        global_copy = self.home / verifier.ENTRY
        global_copy.parent.mkdir(parents=True)
        shutil.copytree(self.vendor, global_copy)
        self.entry.symlink_to(global_copy, target_is_directory=True)
        self.assertEqual(verifier.verify(self.project)["code"], "GLOBAL_DEPENDENCY_REJECTED")

    def test_project_passes_despite_different_global_copy(self):
        self.copied()
        global_copy = self.home / verifier.ENTRY
        global_copy.mkdir(parents=True)
        (global_copy / "SKILL.md").write_text("wrong global version")
        self.assertEqual(verifier.verify(self.project)["status"], "PASS")

    def test_missing_resource_rejected(self):
        self.copied()
        (self.entry / "domain.md").unlink()
        self.assertEqual(verifier.verify(self.project)["code"], "DEPENDENCY_TREE_MISMATCH")

    def test_modified_content_rejected_and_preserved(self):
        self.copied()
        doc = self.entry / "domain.md"
        doc.write_text("Owner edit")
        self.assertEqual(verifier.verify(self.project)["code"], "DEPENDENCY_TREE_MISMATCH")
        self.assertEqual(doc.read_text(), "Owner edit")

    def test_extra_file_rejected(self):
        self.copied()
        (self.entry / "extra.md").write_text("not in pinned tree")
        self.assertEqual(verifier.verify(self.project)["code"], "DEPENDENCY_TREE_MISMATCH")

    def test_mode_drift_rejected(self):
        self.copied()
        (self.entry / "domain.md").chmod(0o755)
        self.assertEqual(verifier.verify(self.project)["code"], "DEPENDENCY_TREE_MISMATCH")

    def test_inner_symlink_rejected(self):
        self.copied()
        (self.entry / "domain.md").unlink()
        (self.entry / "domain.md").symlink_to(self.vendor / "domain.md")
        with self.assertRaises(ValueError):
            verifier.verify(self.project)

    def test_dangling_entry_is_missing_not_global(self):
        self.entry.symlink_to(self.root / "absent")
        self.assertEqual(verifier.verify(self.project)["code"], "PROJECT_DEPENDENCY_MISSING")
        self.assertTrue(self.entry.is_symlink())

    def test_nested_directory_is_not_project_root(self):
        nested = self.project / "nested"
        nested.mkdir()
        self.assertEqual(verifier.verify(nested)["code"], "INVALID_PROJECT_ROOT")

    def test_fresh_worktree_cannot_use_main_entry(self):
        self.copied()
        self.git(self.project, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "fixture")
        worktree = self.root / "worktree"
        self.git(self.project, "worktree", "add", "--detach", str(worktree))
        self.assertEqual(verifier.verify(worktree)["code"], "PROJECT_DEPENDENCY_MISSING")

    def test_global_intermediate_link_to_valid_vendor_is_rejected(self):
        global_copy = self.home / verifier.ENTRY
        global_copy.parent.mkdir(parents=True)
        global_copy.symlink_to(self.vendor, target_is_directory=True)
        self.entry.symlink_to(global_copy, target_is_directory=True)
        self.assertEqual(verifier.verify(self.project)["code"], "GLOBAL_DEPENDENCY_REJECTED")

    def test_cli_missing_reports_machine_readable_failure(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.project)],
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, 1)
        result = json.loads(p.stdout)
        self.assertEqual(result["code"], "PROJECT_DEPENDENCY_MISSING")
        self.assertFalse(result["writes"])


if __name__ == "__main__":
    unittest.main()
