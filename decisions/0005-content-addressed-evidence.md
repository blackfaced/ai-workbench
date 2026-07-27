# 0005 - Keep Run Evidence Complete but Bounded

- Status: accepted
- Date: 2026-07-26

## Context

Unattended Runs may produce large command output, browser captures, image-build
logs, and Kubernetes artifacts. Keeping those bytes inline in SQLite makes the
status and report hot paths grow without bound. Dropping or truncating the
originals would make failures impossible to audit after a retry or daemon
restart.

## Decision

AI Workbench stores large Evidence as immutable, content-addressed objects under
the configured state directory:

- the artifact identifier is its lowercase SHA-256 digest;
- the recorded reference includes the digest, byte length, media type, and
  reader-facing label;
- command stdout and stderr retain at most 4 KiB inline, using a deterministic
  head/tail summary when the full value is larger;
- complete bytes are returned only by an explicit Run-scoped Evidence request;
- reads verify both the recorded size and digest before returning UTF-8 or
  base64 content;
- local, browser, image, and Kubernetes adapters cross the same EvidenceStore
  boundary;
- Todo Evidence is append-only, so a later passing retry does not erase an
  earlier failure or its resource consumption;
- old reports that contain only inline output remain readable.

Objects are retained indefinitely by default. Deletion is an explicit
operator action through `aiwb evidence prune --older-than-days N`; there is no
automatic retention timer in the daemon. Pruning is based on object-file age
and reports exactly which content-addressed objects were removed.

## Consequences

Routine status, report, CLI, and MCP responses stay bounded while preserving
durable references. A daemon restart can reconstruct every reference and
verify or retrieve the same bytes from the state directory. Operators must
budget disk space and choose when to prune. Removing an object intentionally
leaves its immutable reference in historical Run metadata, so a later explicit
read fails clearly instead of silently returning incomplete content.
