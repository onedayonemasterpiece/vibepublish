"""Private verified image ingress; URL/upload-ticket ingress is deliberately gated."""
from __future__ import annotations
import hashlib
import io
import warnings
from dataclasses import dataclass
from PIL import Image, ImageOps, UnidentifiedImageError
from .domain import DomainError, new_id


@dataclass(frozen=True, slots=True)
class VerifiedImage:
    original: bytes
    original_mime: str
    data: bytes
    mime: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class AssetPreview:
    metadata: dict
    data: bytes


PREVIEW_MAX_EDGE = 768
PREVIEW_MAX_BYTES = 384 * 1024
INGRESS_IMAGE_MAX_BYTES = 20 * 1024 * 1024
VERIFIED_IMAGE_MAX_BYTES = INGRESS_IMAGE_MAX_BYTES


def verify_image(data: bytes, mime: str, *, max_input_bytes: int = INGRESS_IMAGE_MAX_BYTES) -> VerifiedImage:
    if type(max_input_bytes) is not int or not 1 <= max_input_bytes <= 32 * 1024 * 1024:
        raise ValueError('invalid image byte limit')
    if not isinstance(data, bytes) or not 1 <= len(data) <= max_input_bytes:
        raise DomainError('asset_size_limit', f'Image input exceeds the {max_input_bytes // (1024 * 1024)} MiB limit')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                actual = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(image.format)
                if actual != mime or image.width * image.height > 25_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise DomainError('asset_format_or_dimensions')
                image.load()
                # A separate immutable sanitized derivative strips EXIF/location.
                oriented = ImageOps.exif_transpose(image)
                clean = Image.new('RGB', oriented.size, 'white')
                if 'A' in oriented.getbands() or 'transparency' in oriented.info:
                    rgba = oriented.convert('RGBA')
                    clean.paste(rgba, mask=rgba.getchannel('A'))
                else:
                    clean.paste(oriented.convert('RGB'))
                output = io.BytesIO()
                clean.save(output, format='PNG')
                verified = output.getvalue()
                derivative_mime = 'image/png'
                if len(verified) > VERIFIED_IMAGE_MAX_BYTES:
                    output = io.BytesIO()
                    clean.save(output, format='JPEG', quality=92)
                    verified = output.getvalue()
                    derivative_mime = 'image/jpeg'
                width, height = clean.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DomainError('invalid_image') from exc
    if len(verified) > VERIFIED_IMAGE_MAX_BYTES:
        raise DomainError('asset_size_limit', 'Sanitized image exceeds the 20 MiB limit')
    return VerifiedImage(data, mime, verified, derivative_mime, width, height)


def insert_verified_image(store, db, actor, image: VerifiedImage) -> str:
    data, mime, verified, width, height = image.original, image.original_mime, image.data, image.width, image.height
    store.current(db, actor)
    source_hash = hashlib.sha256(data).hexdigest()
    verified_hash = hashlib.sha256(verified).hexdigest()
    existing = db.execute(
        """SELECT id,bytes FROM assets
           WHERE tenant_id=? AND principal_id=? AND source_sha256=? AND sha256=?
             AND mime=? AND width=? AND height=?
           ORDER BY created DESC""",
        (actor.tenant_id, actor.principal_id, source_hash, verified_hash, image.mime, width, height),
    ).fetchall()
    for row in existing:
        stored = row['bytes']
        if stored == verified and hashlib.sha256(stored).hexdigest() == verified_hash:
            return row['id']
    used = db.execute('SELECT COALESCE(SUM(length(bytes)),0) FROM assets WHERE tenant_id=?', (actor.tenant_id,)).fetchone()[0]
    quota = db.execute('SELECT storage_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
    if used + len(verified) + len(data) > quota:
        raise DomainError('storage_quota_exceeded')
    original = new_id('asset')
    db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
               (original, actor.tenant_id, actor.principal_id, source_hash, mime, width, height, data, source_hash, store.clock()))
    derivative = new_id('asset')
    db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
               (derivative, actor.tenant_id, actor.principal_id, verified_hash,
                image.mime, width, height, verified, source_hash, store.clock()))
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



def expired_native_intent(created, scheduled_at, now):
    from .domain import parse_time
    return now - max(created, parse_time(scheduled_at) if scheduled_at else created) >= 3 * 86400


def stale_unsent_attempts(db, now):
    """Expired never-dispatched public commands; no provider/browser required."""
    from .domain import parse_time
    rows = db.execute(
        """SELECT a.id AS attempt_id,o.id AS operation_id,a.alias,a.provider,
                  o.created,json_extract(a.plan,'$.scheduled_at') AS scheduled_at
           FROM attempts a JOIN operations o ON o.id=a.operation_id
           JOIN publications p ON p.id=o.publication_id
           WHERE o.complete=0 AND o.work_state IN ('ready','working')
             AND o.lease_until<=? AND p.kind!='media_store'
             AND o.action IN ('publish','publication_update')
             AND a.dispatched=0 AND a.state IN ('accepted','running','blocked')""",
        (now,),
    )
    found = []
    for row in rows:
        if expired_native_intent(row['created'], row['scheduled_at'], now):
            start = max(row['created'], parse_time(row['scheduled_at']) if row['scheduled_at'] else row['created'])
            found.append({**dict(row), 'age_days': (now - start) / 86400})
    return found


def retired_asset_rows(db, now, *, include_sizes=True):
    """One transaction's local-byte retention decision; native media is canonical."""
    stale = {row['attempt_id'] for row in stale_unsent_attempts(db, now)}
    refs, pending, uncertain, failed = set(), set(), set(), set()
    for ref, attempt_id, work, operation_state, attempt_state, created, seen, scheduled in db.execute(
        """SELECT json_extract(j.value,'$.ref'),t.id,o.work_state,o.state,t.state,
                  o.created,o.worker_seen,json_extract(t.plan,'$.scheduled_at')
           FROM attempts t JOIN operations o ON o.id=t.operation_id
           JOIN json_each(t.plan,'$.assets') j"""
    ):
        if not ref:
            continue
        refs.add(ref)
        # Terminal failures/unknown effects age from their last worker observation,
        # never from a future provider schedule; no retry is allowed for unknown.
        last = max(created, seen or created)
        if work != 'done' and attempt_id not in stale:
            pending.add(ref)
        elif now - last < 3 * 86400:
            if operation_state == 'outcome_unknown' or attempt_state == 'outcome_unknown':
                uncertain.add(ref)
            elif attempt_state in {'blocked', 'failed'} and attempt_id not in stale:
                failed.add(ref)

    def refset(sql, params=()):
        return {row[0] for row in db.execute(sql, params) if row[0]}

    transfer = refset("SELECT asset_id FROM media_store_assets WHERE expires>?", (now,))
    story = refset("""SELECT json_extract(j.value,'$.ref') FROM vk_story_dependencies d,
                              json_each(d.story_plan,'$.assets') j
                       WHERE d.state IN ('waiting','queued')""")
    # Visual jobs can still require their input while their operation is pending.
    pending |= refset("""SELECT json_extract(s.value,'$.ref')
                        FROM visual_jobs v JOIN operations o ON o.id=v.operation_id,
                             json_each(v.sources) s WHERE o.work_state!='done'""")
    pending |= refset("""SELECT c.asset_ref FROM visual_candidates c
                        JOIN visual_jobs v ON v.id=c.job_id
                        JOIN operations o ON o.id=v.operation_id WHERE o.work_state!='done'
                        UNION SELECT c.art_ref FROM visual_candidates c
                        JOIN visual_jobs v ON v.id=c.job_id
                        JOIN operations o ON o.id=v.operation_id WHERE o.work_state!='done'""")
    visual = refset("""SELECT asset_ref FROM visual_candidates
                       UNION SELECT art_ref FROM visual_candidates
                       UNION SELECT asset_id FROM visual_asset_origins""")
    emoji = refset("SELECT asset_id FROM emoji_asset_origins")
    rows = []
    source = ("SELECT id,length(bytes),created FROM assets" if include_sizes else
              "SELECT id,0,created FROM assets INDEXED BY assets_retention_lookup")
    for ident, size, created in db.execute(source):
        if ident in transfer:
            reason = 'media_transfer'
        elif ident in pending:
            reason = 'pending_action'
        elif ident in story:
            reason = 'pending_linked_story'
        elif ident in uncertain:
            reason = 'recent_unknown'
        elif ident in failed:
            reason = 'recent_failure'
        elif ident in emoji:
            reason = 'emoji_catalog'
        elif ident in visual and created >= now - 14 * 86400:
            reason = 'recent_visual'
        elif ident not in refs and created >= now - 14 * 86400:
            reason = 'recent_unlinked'
        else:
            reason = 'reclaim'
        rows.append({'id': ident, 'size_bytes': size, 'reason': reason, 'created': created})

    # One candidate may reference two asset rows, sometimes shared with others.
    # Never delete one while a retained candidate still has a foreign key to it.
    by_id = {row['id']: row for row in rows}
    pairs = list(db.execute("SELECT asset_ref,art_ref FROM visual_candidates"))
    for _ in range(len(pairs) + 1):
        changed = False
        for left, right in pairs:
            if (left in by_id and right in by_id
                    and (by_id[left]['reason'] != 'reclaim' or by_id[right]['reason'] != 'reclaim')):
                for ref in (left, right):
                    if by_id[ref]['reason'] == 'reclaim':
                        by_id[ref]['reason'] = 'visual_lineage_held'
                        changed = True
        if not changed:
            break
    return rows


def reclaim_asset_bytes(db, rows):
    """Remove eligible local copies and their visual FK metadata, never native facts."""
    retiring = {row['id'] for row in rows if row['reason'] == 'reclaim'}
    if not retiring:
        return
    for candidate_id, image, art in db.execute(
        "SELECT id,asset_ref,art_ref FROM visual_candidates"
    ).fetchall():
        if image in retiring or art in retiring:
            if image not in retiring or art not in retiring:
                raise DomainError('visual_lineage_held')
            db.execute("DELETE FROM visual_feedback WHERE candidate_id=?", (candidate_id,))
            db.execute("DELETE FROM visual_candidates WHERE id=?", (candidate_id,))
    db.executemany("DELETE FROM visual_asset_origins WHERE asset_id=?",
                   [(ident,) for ident in retiring])
    db.executemany("DELETE FROM assets WHERE id=?", [(ident,) for ident in retiring])


def import_image(store, actor, data: bytes, mime: str) -> str:
    image = verify_image(data, mime)
    with store.tx() as db:
        return insert_verified_image(store, db, actor, image)
