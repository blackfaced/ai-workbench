from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple


_ARTIFACT_ID = re.compile(r"[0-9a-f]{64}")
_INLINE_LIMIT_BYTES = 4096


class EvidenceError(RuntimeError):
    pass


class EvidenceIntegrityError(EvidenceError):
    pass


@dataclass(frozen=True)
class EvidenceReference:
    artifact_id: str
    sha256: str
    size_bytes: int
    media_type: str
    label: str


@dataclass(frozen=True)
class EvidencePayload:
    reference: EvidenceReference
    encoding: str
    content: str

    def to_dict(self) -> dict[str, object]:
        return {
            "reference": {
                "artifact_id": self.reference.artifact_id,
                "sha256": self.reference.sha256,
                "size_bytes": self.reference.size_bytes,
                "media_type": self.reference.media_type,
                "label": self.reference.label,
            },
            "encoding": self.encoding,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "EvidencePayload":
        reference = value.get("reference")
        if not isinstance(reference, dict):
            raise ValueError("Evidence payload reference must be a mapping")
        return cls(
            reference=EvidenceReference(
                artifact_id=str(reference["artifact_id"]),
                sha256=str(reference["sha256"]),
                size_bytes=int(reference["size_bytes"]),
                media_type=str(
                    reference.get("media_type", "application/octet-stream")
                ),
                label=str(reference.get("label", "")),
            ),
            encoding=str(value["encoding"]),
            content=str(value["content"]),
        )


@dataclass(frozen=True)
class EvidencePruneReport:
    scanned: int
    deleted: int
    retained: int
    older_than_days: int


class EvidenceStore:
    """Retain immutable, content-addressed Evidence outside checkpoint payloads."""

    def __init__(self, state_dir: Path) -> None:
        self._root = Path(state_dir).expanduser().resolve() / "evidence" / "objects"

    def retain_text(
        self,
        content: str,
        *,
        label: str,
        media_type: str = "text/plain; charset=utf-8",
    ) -> Tuple[str, Optional[EvidenceReference]]:
        encoded = content.encode("utf-8")
        if len(encoded) <= _INLINE_LIMIT_BYTES:
            return content, None
        reference = self.retain_bytes(
            encoded,
            label=label,
            media_type=media_type,
        )
        marker = (
            f"\n...[truncated; full Evidence {reference.artifact_id}; "
            f"{reference.size_bytes} bytes]...\n"
        )
        marker_bytes = marker.encode("utf-8")
        remaining = max(0, _INLINE_LIMIT_BYTES - len(marker_bytes))
        prefix_size = remaining * 2 // 3
        suffix_size = remaining - prefix_size
        summary = (
            encoded[:prefix_size].decode("utf-8", errors="ignore")
            + marker
            + encoded[-suffix_size:].decode("utf-8", errors="ignore")
        )
        while len(summary.encode("utf-8")) > _INLINE_LIMIT_BYTES:
            summary = summary[:-1]
        return summary, reference

    def retain_file(
        self,
        path: Path,
        *,
        label: str,
    ) -> EvidenceReference:
        path = Path(path).expanduser().resolve()
        try:
            content = path.read_bytes()
        except OSError as error:
            raise EvidenceError(f"cannot retain Evidence artifact {path}: {error}") from error
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return self.retain_bytes(
            content,
            label=label,
            media_type=media_type,
        )

    def retain_bytes(
        self,
        content: bytes,
        *,
        label: str,
        media_type: str,
    ) -> EvidenceReference:
        digest = hashlib.sha256(content).hexdigest()
        path = self.object_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                str(path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            descriptor = -1
        if descriptor >= 0:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
        return EvidenceReference(
            artifact_id=digest,
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
            label=label,
        )

    def read(
        self,
        artifact_id: str,
        *,
        reference: Optional[EvidenceReference] = None,
    ) -> EvidencePayload:
        path = self.object_path(artifact_id)
        try:
            content = path.read_bytes()
        except OSError as error:
            raise EvidenceError(
                f"Evidence artifact is unavailable: {artifact_id}: {error}"
            ) from error
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact_id:
            raise EvidenceIntegrityError(
                f"Evidence digest mismatch for {artifact_id}: observed {digest}"
            )
        if reference is not None:
            if reference.sha256 != digest or reference.size_bytes != len(content):
                raise EvidenceIntegrityError(
                    f"Evidence metadata mismatch for {artifact_id}"
                )
        else:
            reference = EvidenceReference(
                artifact_id=artifact_id,
                sha256=digest,
                size_bytes=len(content),
                media_type="application/octet-stream",
                label="",
            )
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            encoding = "base64"
            decoded = base64.b64encode(content).decode("ascii")
        else:
            encoding = "utf-8"
        return EvidencePayload(
            reference=reference,
            encoding=encoding,
            content=decoded,
        )

    def object_path(self, artifact_id: str) -> Path:
        if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise ValueError("Evidence artifact_id must be 64 lowercase hex characters")
        return self._root / artifact_id[:2] / artifact_id

    def prune(self, older_than_days: int) -> EvidencePruneReport:
        if (
            isinstance(older_than_days, bool)
            or not isinstance(older_than_days, int)
            or older_than_days <= 0
        ):
            raise ValueError("older_than_days must be a positive integer")
        cutoff = time.time() - older_than_days * 86400
        scanned = 0
        deleted = 0
        if self._root.is_dir():
            for path in self._root.glob("*/*"):
                if not path.is_file() or not _ARTIFACT_ID.fullmatch(path.name):
                    continue
                scanned += 1
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted += 1
        return EvidencePruneReport(
            scanned=scanned,
            deleted=deleted,
            retained=scanned - deleted,
            older_than_days=older_than_days,
        )
