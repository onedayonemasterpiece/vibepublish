"""Saved cutouts must retain their private source through normal asset cleanup."""
import hashlib
import io

from PIL import Image

from social_operations.assets import import_image, reclaim_asset_bytes, retired_asset_rows
from social_operations.carousel import CarouselService
from social_operations.service import Application
from social_operations.storage import Store


def test_saved_alpha_revision_survives_cleanup_without_retaining_foreign_sources(tmp_path):
    now = [1_800_000_000.0]
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    app = Application(store)
    service = CarouselService(app)
    cutout = Image.new('RGBA', (100, 60), (255, 255, 255, 0))
    cutout.paste((240, 45, 25, 255), (20, 15, 84, 45))
    output = io.BytesIO()
    cutout.save(output, format='PNG')
    source = output.getvalue()
    source_sha = hashlib.sha256(source).hexdigest()
    asset = import_image(store, actor, source, 'image/png')

    # Identical bytes owned elsewhere must not become this story's dependencies.
    for tenant, label in (('tenant', 'other'), ('other-tenant', 'other-owner')):
        other = store.authenticate(store.create_principal(tenant, label, owner=True))
        import_image(store, other, source, 'image/png')
    unused = io.BytesIO()
    Image.new('RGBA', (12, 12), (10, 20, 30, 40)).save(unused, format='PNG')
    unused_sha = hashlib.sha256(unused.getvalue()).hexdigest()
    import_image(store, actor, unused.getvalue(), 'image/png')
    with store.connection() as db:
        original = db.execute('SELECT id FROM assets WHERE tenant_id=? AND principal_id=? AND sha256=?',
            (actor.tenant_id, actor.principal_id, source_sha)).fetchone()['id']
        unreferenced = {row[0] for row in db.execute(
            'SELECT id FROM assets WHERE principal_id!=? OR source_sha256=?',
            (actor.principal_id, unused_sha))}

    background = ('<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
                  '<rect width="384" height="160" fill="#173957"/>')
    created = service.command(actor, {'command': {'kind': 'create', 'brief': 'Вырезка через шов',
        'card_count': 3, 'card_width': 128, 'card_height': 160,
        'svg': background + f'<image href="asset:{asset}" x="90" y="20" width="100" height="60"/></svg>'},
        'request_key': 'alpha-story'})
    ident = created['carousel_id']
    render = {'command': {'kind': 'render', 'carousel_id': ident, 'revision': 1,
                          'view': 'region', 'region': [90, 20, 100, 60]}}
    before = Image.open(io.BytesIO(service.command(actor, render).data)).convert('RGB')
    export = {'kind': 'export', 'carousel_id': ident, 'revision': 1}
    first = service.command(actor, {'command': export, 'request_key': 'before-cleanup'})
    # A source used only by an older saved revision is still needed for reopening it.
    service.command(actor, {'command': {'kind': 'revise', 'carousel_id': ident,
        'expected_revision': 1, 'svg': background + '</svg>'}, 'request_key': 'without-cutout'})

    now[0] += 15 * 86400
    with store.tx() as db:
        reclaim_asset_bytes(db, retired_asset_rows(db, now[0], include_sizes=False))
        remaining = {row[0] for row in db.execute('SELECT id FROM assets')}
    after = Image.open(io.BytesIO(service.command(actor, render).data)).convert('RGB')
    assert after.getpixel((2, 2)) == (23, 57, 87)  # The canvas, not a white derivative.
    assert after.getpixel((29, 30)) == after.getpixel((51, 30)) == (240, 45, 25)
    assert after.tobytes() == before.tobytes()
    assert {asset, original} <= remaining
    assert not unreferenced & remaining
    # A new export key forces a fresh render; replay alone could hide source loss.
    second = service.command(actor, {'command': export, 'request_key': 'after-cleanup'})
    assert [card['sha256'] for card in second['cards']] == [card['sha256'] for card in first['cards']]
