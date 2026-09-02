from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from aiwb.harness import HarnessRequest  # noqa: E402
from aiwb.image import CommandImageBuilder, ImageBuildRequest  # noqa: E402
from aiwb.kubernetes import KubernetesHarness  # noqa: E402
from aiwb.project import (  # noqa: E402
    CandidatePublishProfile,
    HarnessProfile,
    ImageProfile,
)
from aiwb.publish import CandidatePublishRequest, CandidatePublisher  # noqa: E402


def test_image_builder_retains_an_immutable_digest_and_operation_artifacts() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        start = (sys.executable, "-c", 'print("{\\\"operation_id\\\":\\\"op-1\\\"}")')
        status = (sys.executable, "-c", 'print("{\\\"status\\\":\\\"succeeded\\\"}")')
        result = (sys.executable, "-c", 'print("{\\\"digest\\\":\\\"sha256:' + "a" * 64 + '\\\",\\\"artifacts\\\":[\\\"remote.log\\\"]}")')
        request = ImageBuildRequest(ImageProfile("candidate", "non-production", start, status, result), root, "run-1", root / "artifacts")
        builder = CommandImageBuilder()

        operation = builder.start(request)
        assert builder.status(request, operation) == "succeeded"
        image = builder.result(request, operation)

        assert image.digest == "sha256:" + "a" * 64
        assert "remote.log" in image.artifacts
        assert len(tuple((root / "artifacts").glob("*.stdout.log"))) == 3


def test_kubernetes_harness_uses_project_commands_and_always_cleans_up() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        events = root / "events.txt"
        provision = (sys.executable, "-c", 'print("{\\\"base_url\\\":\\\"https://example.test\\\"}")')
        collect = (sys.executable, "-c", 'print("{\\\"artifacts\\\":[]}")')
        cleanup = (sys.executable, "-c", 'print("{\\\"cleaned\\\":true}")')
        profile = HarnessProfile("development", "kubernetes", "non-production", kubernetes_context="development", namespace_prefix="aiwb", ttl_seconds=60, provision_command=provision, collect_command=collect, cleanup_command=cleanup)

        execution = KubernetesHarness(root / "state").execute(HarnessRequest(profile, (sys.executable, "-c", "raise SystemExit(0)"), root, 30, "run-1", root / "artifacts", "attempt-1", "verification"))

        assert execution.returncode == 0
        assert execution.environment.startswith("non-production/development/aiwb-run-1-")
        assert not list((root / "state" / "kubernetes-leases").glob("*.json"))
        assert not events.exists()


def test_candidate_publisher_pushes_only_the_exact_candidate_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository, remote = root / "repository", root / "remote.git"
        repository.mkdir()
        for command in (("git", "init", "-b", "main"), ("git", "config", "user.name", "AIWB"), ("git", "config", "user.email", "aiwb@example.test")):
            subprocess.run(command, cwd=repository, check=True, capture_output=True)
        (repository / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(("git", "add", "."), cwd=repository, check=True)
        subprocess.run(("git", "commit", "-m", "fixture"), cwd=repository, check=True, capture_output=True)
        subprocess.run(("git", "init", "--bare", str(remote)), check=True, capture_output=True)
        subprocess.run(("git", "remote", "add", "origin", str(remote)), cwd=repository, check=True)
        commit = subprocess.run(("git", "rev-parse", "HEAD"), cwd=repository, check=True, text=True, capture_output=True).stdout.strip()

        published = CandidatePublisher().publish(CandidatePublishRequest(repository, "aiwb/run-1", commit, CandidatePublishProfile("origin", "aiwb/")))

        assert published.commit == commit
        assert published.ref == "refs/heads/aiwb/run-1"
