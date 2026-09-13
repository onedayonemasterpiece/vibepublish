"""Trusted same-host import from the my-browser-bridge exact-byte artifact store."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from .asset_ingress import MAX_UPLOAD_BYTES
from .assets import insert_verified_image, verify_image
from .domain import DomainError, digest


ACTION = "browser_artifact_import"
ROOT_ENV = "VIBEPUBLISH_BROWSER_ARTIFACT_ROOT"
_URI = re.compile(
    r"^artifact://([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
_MAX_METADATA_BYTES = 64 * 1024
_OPEN_BASE = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_OPEN_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _artifact_root() -> Path:
    raw = os.environ.get(ROOT_ENV, "")
    if not raw:
        raise DomainError("browser_artifact_config_missing", next_action="contact_owner")
    root = Path(raw)
    if not root.is_absolute():
        raise DomainError("browser_artifact_config_invalid", next_action="contact_owner")
    try:
        info = os.lstat(root)
    except OSError:
        raise DomainError("browser_artifact_config_invalid", next_action="contact_owner") from None
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise DomainError("browser_artifact_config_invalid", next_action="contact_owner")
    return root


def _read_regular_at(directory_fd: int, name: str, maximum: int, *, size_code: str) -> tuple[bytes, int]:
    try:
        fd = os.open(name, _OPEN_BASE | _OPEN_NOFOLLOW, dir_fd=directory_fd)
    except FileNotFoundError:
        raise DomainError("browser_artifact_not_found") from None
    except OSError:
        raise DomainError("browser_artifact_invalid") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise DomainError("browser_artifact_invalid")
        if info.st_size < 1:
            raise DomainError("browser_artifact_invalid")
        if info.st_size > maximum:
            raise DomainError(size_code)
        remaining = info.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise DomainError("browser_artifact_integrity")
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != info.st_size:
            raise DomainError("browser_artifact_integrity")
        return data, info.st_size
    finally:
        os.close(fd)


def _metadata(data: bytes, artifact_id: str, uri: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise DomainError("browser_artifact_invalid") from None
    if not isinstance(value, dict):
        raise DomainError("browser_artifact_invalid")
    size = value.get("size")
    filename = value.get("fileName")
    mime = value.get("mediaType")
    sha256 = value.get("sha256")
    if (
        value.get("id") != artifact_id
        or value.get("uri") != uri
        or value.get("kind") != "image"
        or not isinstance(filename, str)
        or not 1 <= len(filename) <= 180
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
        or mime not in _ALLOWED_MIME
        or type(size) is not int
        or size < 1
        or not isinstance(sha256, str)
        or not _SHA256.fullmatch(sha256)
    ):
        if isinstance(mime, str) and mime not in _ALLOWED_MIME:
            raise DomainError("browser_artifact_mime_unsupported")
        raise DomainError("browser_artifact_invalid")
    if size > MAX_UPLOAD_BYTES:
        raise DomainError("asset_size_limit")
    return value


def load_browser_artifact(uri: str) -> tuple[bytes, str, str]:
    match = _URI.fullmatch(uri) if isinstance(uri, str) else None
    if not match:
        raise DomainError("browser_artifact_uri_invalid")
    artifact_id = match.group(1)
    root = _artifact_root()
    try:
        root_fd = os.open(root, _OPEN_BASE | _OPEN_DIRECTORY | _OPEN_NOFOLLOW)
    except OSError:
        raise DomainError("browser_artifact_config_invalid", next_action="contact_owner") from None
    try:
        try:
            artifact_fd = os.open(
                artifact_id,
                _OPEN_BASE | _OPEN_DIRECTORY | _OPEN_NOFOLLOW,
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            raise DomainError("browser_artifact_not_found") from None
        except OSError:
            raise DomainError("browser_artifact_invalid") from None
        try:
            metadata_bytes, _ = _read_regular_at(
                artifact_fd,
                "metadata.json",
                _MAX_METADATA_BYTES,
                size_code="browser_artifact_invalid",
            )
            metadata = _metadata(metadata_bytes, artifact_id, uri)
            payload, payload_size = _read_regular_at(
                artifact_fd,
                "payload",
                MAX_UPLOAD_BYTES,
                size_code="asset_size_limit",
            )
        finally:
            os.close(artifact_fd)
    finally:
        os.close(root_fd)
    if payload_size != metadata["size"] or hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
        raise DomainError("browser_artifact_integrity")
    return payload, metadata["mediaType"], metadata["sha256"]


def _authority(store, db, actor):
    actor = store.current(db, actor)
    if not actor.scopes.intersection({"publish", "visual"}):
        raise DomainError("access_denied")
    return actor


async def import_browser_artifact(service, actor, args):
    store = service.store
    uri = args["command"]["uri"]
    key = args["request_key"]
    intent = {"artifact_uri": uri}
    with store.connection() as db:
        actor = _authority(store, db, actor)
        op = service._replay(db, actor, ACTION, intent, {"request_key": key}, implicit=False)
    if op:
        return store.receipt(actor, op)

    data, mime, source_sha256 = await run_in_threadpool(load_browser_artifact, uri)
    image = await run_in_threadpool(verify_image, data, mime)
    if hashlib.sha256(data).hexdigest() != source_sha256:
        raise DomainError("browser_artifact_integrity")

    with store.tx() as db:
        actor = _authority(store, db, actor)
        op = service._replay(db, actor, ACTION, intent, {"request_key": key}, implicit=False)
        if not op:
            ident = insert_verified_image(store, db, actor, image)
            row = db.execute("SELECT source_sha256 FROM assets WHERE id=?", (ident,)).fetchone()
            if not row or row["source_sha256"] != source_sha256:
                raise DomainError("asset_integrity")
            op = service._new_operation(
                db,
                actor,
                ACTION,
                intent,
                complete=True,
                result={"resource_id": ident},
            )
            service._key(db, actor, key, digest([ACTION, intent]), op)
    return store.receipt(actor, op)
