#!/usr/bin/env python3
"""POSIX locks and optimistic atomic writes for the project-context renderer."""
import contextlib
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import fcntl


def guard(path):
    """Refuse symlinks at every ancestor and foreign/non-regular targets."""
    p = Path(os.path.abspath(path))
    for q in [p] + list(p.parents):
        if q.is_symlink():
            raise RuntimeError('symlink refused: %s' % q)
        if q.exists():
            st = q.stat()
            if q == p and not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise RuntimeError('non-regular target refused: %s' % q)
            if q == p and st.st_uid != os.getuid():
                raise RuntimeError('foreign-owned target refused: %s' % q)
    if p.exists() and (not os.access(p, os.W_OK) or not p.stat().st_mode & 0o222):
        raise RuntimeError('read-only target refused: %s' % p)
    return str(p)


def fingerprint(path):
    guard(path)
    p = Path(path)
    if not p.exists():
        return None
    if not p.is_file():
        raise RuntimeError('target is not a regular file: %s' % path)
    return hashlib.sha256(p.read_bytes()).hexdigest()


@contextlib.contextmanager
def locks(paths):
    """Sorted per-resource flock keys serialize different projects sharing trust.

    Cooperating writers hold these locks through planning, writes and ledger flush.
    Ordinary editors do not flock; atomic_write additionally compares a digest.
    """
    root = Path.home().resolve() / '.local/state/setup-aiwb/project-context-locks'
    guard(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    handles = []
    try:
        for p in sorted(set(os.path.realpath(p) for p in paths)):
            key = root / (hashlib.sha256(p.encode()).hexdigest() + '.lock')
            guard(key)
            fd = os.open(str(key), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            h = os.fdopen(fd, 'a+')
            handles.append(h)
            fcntl.flock(h, fcntl.LOCK_EX)
        yield
    finally:
        for h in reversed(handles):
            fcntl.flock(h, fcntl.LOCK_UN)
            h.close()


_UNSET = object()


def atomic_write(path, data, expected=_UNSET):
    """Unique same-directory temp, fsync, guard + digest before replace.

    No portable filesystem API provides CAS against non-cooperating editors. The
    check narrows, but cannot eliminate, the final check/rename race; report it.
    """
    path = guard(path)
    old = fingerprint(path) if expected is _UNSET else expected
    parent = os.path.dirname(path)
    guard(parent)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.aiwb-context-', dir=parent)
    try:
        if os.path.isfile(path):
            os.fchmod(fd, stat.S_IMODE(os.stat(path).st_mode))
        with os.fdopen(fd, 'wb') as h:
            h.write(data if isinstance(data, bytes) else data.encode('utf-8'))
            h.flush()
            os.fsync(h.fileno())
        guard(path)
        if fingerprint(path) != old:
            raise RuntimeError('target drifted between observation and write: %s' % path)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
