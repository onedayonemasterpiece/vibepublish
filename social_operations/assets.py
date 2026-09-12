"""Private verified image ingress; URL/upload-ticket ingress is deliberately gated."""
from __future__ import annotations
import hashlib
import io
import warnings
from dataclasses import dataclass
from PIL import Image, UnidentifiedImageError
from .domain import DomainError, new_id


@dataclass(frozen=True, slots=True)
class VerifiedImage:
    original: bytes
    original_mime: str
    data: bytes
    width: int
    height: int


def verify_image(data: bytes, mime: str) -> VerifiedImage:
    if not isinstance(data, bytes) or not 1 <= len(data) <= 20 * 1024 * 1024:
        raise DomainError('asset_size_limit')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                actual = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(image.format)
                if actual != mime or image.width * image.height > 25_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise DomainError('asset_format_or_dimensions')
                image.load()
                # A separate immutable sanitized derivative strips EXIF/location.
                clean = Image.new('RGB', image.size)
                clean.paste(image.convert('RGB'))
                output = io.BytesIO()
                clean.save(output, format='PNG')
                verified = output.getvalue()
                width, height = clean.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DomainError('invalid_image') from exc
    if len(verified) > 32 * 1024 * 1024:
        raise DomainError('asset_size_limit')
    return VerifiedImage(data, mime, verified, width, height)


def insert_verified_image(store, db, actor, image: VerifiedImage) -> str:
    data, mime, verified, width, height = image.original, image.original_mime, image.data, image.width, image.height
    store.current(db, actor)
    used = db.execute('SELECT COALESCE(SUM(length(bytes)),0) FROM assets WHERE tenant_id=?', (actor.tenant_id,)).fetchone()[0]
    quota = db.execute('SELECT storage_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
    if used + len(verified) + len(data) > quota:
        raise DomainError('storage_quota_exceeded')
    original = new_id('asset')
    source_hash = hashlib.sha256(data).hexdigest()
    db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
               (original, actor.tenant_id, actor.principal_id, source_hash, mime, width, height, data, source_hash, store.clock()))
    derivative = new_id('asset')
    db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
               (derivative, actor.tenant_id, actor.principal_id, hashlib.sha256(verified).hexdigest(),
                'image/png', width, height, verified, source_hash, store.clock()))
    return derivative



def import_image(store, actor, data: bytes, mime: str) -> str:
    image = verify_image(data, mime)
    with store.tx() as db:
        return insert_verified_image(store, db, actor, image)
