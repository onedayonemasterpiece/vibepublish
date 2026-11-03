"""Exclusive existing browser-profile ownership; attempts live in the core ledger."""
from __future__ import annotations

import fcntl
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

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
