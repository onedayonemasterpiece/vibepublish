"""Private, compare-and-swap MAX allowlist registration under the profile lease."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import uuid

from .live import Target
from .profile import MaxBlocked


def _safe_info(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
        raise MaxBlocked("unsafe_binding_permissions")


def _read_at(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        _safe_info(os.fstat(fd))
        with os.fdopen(fd, closefd=False) as stream:
            return json.load(stream)
    finally:
        os.close(fd)


def _replace(directory, name, expected, value):
    if _read_at(directory, name) != expected:
        raise MaxBlocked("binding_changed")
    temporary = "." + name + "." + uuid.uuid4().hex
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        if _read_at(directory, name) != expected:
            raise MaxBlocked("binding_changed")
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


@contextmanager
def register(driver, evidence):
    """Rollback on ledger failure; crash leftovers have no new core authority.

    The profile lease serializes product processes. The private sibling lock and
    expected document protect cooperating writers; mismatches never overwrite.
    """
    driver.lane.owned()
    if getattr(driver, "_verified_resolution", None) != evidence:
        raise MaxBlocked("resolution_evidence_required")
    if not getattr(driver, "allowlist_path", None):
        raise MaxBlocked("persistent_binding_unavailable")
    path = Path(driver.allowlist_path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise MaxBlocked("unsafe_binding_path")
    target = Target(evidence["native_id"], evidence["label"], "publish_channel")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = None
    changed = False
    previous_target = driver.targets.get(target.native_id)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise MaxBlocked("unsafe_binding_directory")
        lock_fd = os.open("." + path.name + ".bind.lock",
                          os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        _safe_info(os.fstat(lock_fd))
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MaxBlocked("binding_busy") from None
        before = _read_at(directory, path.name)
        if before != driver.binding_snapshot:
            raise MaxBlocked("binding_changed")
        if (not isinstance(before, dict) or not isinstance(before.get("targets"), dict)
                or not isinstance(before.get("account_phone"), str)):
            raise MaxBlocked("invalid_binding_document")
        old = before["targets"].get(target.native_id)
        if old is not None and old.get("policy") != "publish_channel":
            raise MaxBlocked("channel_binding_policy_conflict")
        after = dict(before, targets=dict(before["targets"]))
        after["targets"][target.native_id] = dict(old or {}, alias=target.alias,
                                               policy=target.policy,
                                               public_url=evidence["url"])
        changed = after != before
        if changed:
            _replace(directory, path.name, before, after)
        driver.targets[target.native_id] = target
        driver.binding_snapshot = after
        try:
            yield
        except BaseException:
            if changed:
                _replace(directory, path.name, after, before)
            driver.binding_snapshot = before
            if previous_target is None:
                driver.targets.pop(target.native_id, None)
            else:
                driver.targets[target.native_id] = previous_target
            raise
        finally:
            driver._verified_resolution = None
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory)
