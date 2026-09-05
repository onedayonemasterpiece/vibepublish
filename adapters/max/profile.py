"""Linux profile ownership and conservative side-effect quarantine, not a ledger.

The lock is held across browser launch/close. An unresolved boundary survives
process death and blocks ALL new mutations, even with a new operation identity.
Only core observation/recovery authority may resolve the quarantine.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
from pathlib import Path


class MaxBlocked(Exception):
    """A sanitized reason; never propagate Playwright DOM/error payloads."""


class ProfileLane:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        self.fd = None

    def __enter__(self):
        if self.fd is not None:
            raise MaxBlocked('profile_already_owned')
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise MaxBlocked('unsafe_profile_path')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise MaxBlocked('profile_permissions')
        fd = os.open(self.root / '.vibepublish.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise MaxBlocked('unsafe_lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise MaxBlocked('profile_busy') from None
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        return self

    def owned(self):
        if self.fd is None:
            raise MaxBlocked('profile_not_owned')

    @property
    def marker(self):
        return self.root / '.vibepublish-uncertain'

    def assert_clear(self):
        self.owned()
        if os.path.lexists(self.marker):
            raise MaxBlocked('outcome_unknown')

    def arm(self, attempt_id: str, plan_digest: str):
        self.assert_clear()
        # No target, content, credentials or assets in this safety fuse.
        fd = os.open(self.marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'attempt_id': attempt_id, 'plan_digest': plan_digest}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self._sync_directory()
        except BaseException:
            # Even an incomplete fuse is a quarantine, never safe to resend.
            raise

    def resolve_observed(self):
        """Call only AFTER exact observation has been durably checkpointed."""
        self.owned()
        self.marker.unlink()
        self._sync_directory()

    def _sync_directory(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
