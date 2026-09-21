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


@dataclass(frozen=True, slots=True)
class AssetPreview:
    metadata: dict
    data: bytes


PREVIEW_MAX_EDGE = 768
PREVIEW_MAX_BYTES = 384 * 1024


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
    source_hash = hashlib.sha256(data).hexdigest()
    derivative_hash = hashlib.sha256(verified).hexdigest()
    existing = db.execute(
        "SELECT id FROM assets WHERE tenant_id=? AND principal_id=? AND source_sha256=? "
        "AND sha256=? AND mime='image/png' AND width=? AND height=? ORDER BY created LIMIT 1",
        (actor.tenant_id, actor.principal_id, source_hash, derivative_hash, width, height),
    ).fetchone()
    if existing:
        return existing[0]
    used = db.execute('SELECT COALESCE(SUM(length(bytes)),0) FROM assets WHERE tenant_id=?', (actor.tenant_id,)).fetchone()[0]
    quota = db.execute('SELECT storage_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
    if used + len(verified) + len(data) > quota:
        raise DomainError('storage_quota_exceeded')
    original = new_id('asset')
    db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
               (original, actor.tenant_id, actor.principal_id, source_hash, mime, width, height, data, source_hash, store.clock()))
    derivative = new_id('asset')
    db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
               (derivative, actor.tenant_id, actor.principal_id, derivative_hash,
                'image/png', width, height, verified, source_hash, store.clock()))
    return derivative


def render_asset_preview(data: bytes, source_sha256: str, resource_uri: str) -> AssetPreview:
    """Create a bounded, metadata-free model preview without changing the source asset."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                clean = Image.new('RGB', source.size, 'white')
                if 'A' in source.getbands():
                    clean.paste(source.convert('RGBA'), mask=source.getchannel('A'))
                else:
                    clean.paste(source.convert('RGB'))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DomainError('invalid_image') from exc
    for edge, quality in ((768, 72), (640, 68), (512, 64), (384, 58)):
        preview = clean.copy()
        preview.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        preview.save(output, format='WEBP', quality=quality, method=4, exif=b'')
        encoded = output.getvalue()
        if len(encoded) <= PREVIEW_MAX_BYTES:
            metadata = {
                'resource_uri': resource_uri,
                'source_sha256': source_sha256,
                'preview_sha256': hashlib.sha256(encoded).hexdigest(),
                'mime_type': 'image/webp',
                'width': preview.width,
                'height': preview.height,
                'size_bytes': len(encoded),
            }
            return AssetPreview(metadata, encoded)
    raise DomainError('asset_preview_size_limit')



def import_image(store, actor, data: bytes, mime: str) -> str:
    image = verify_image(data, mime)
    with store.tx() as db:
        return insert_verified_image(store, db, actor, image)
