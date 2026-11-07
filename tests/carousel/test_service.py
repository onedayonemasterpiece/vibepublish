"""A real reference-led edit, exact crops and a replayable private card export."""
import io
import json
import random
import sqlite3

import pytest
from PIL import Image, ImageChops

from social_operations.assets import import_image, reclaim_asset_bytes, retired_asset_rows
from social_operations.carousel import CarouselService
from social_operations.carousel_references import ReferenceBank
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store


@pytest.fixture
def runtime(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    app = Application(store)
    service = CarouselService(app)
    source = Image.new('RGB', (384, 160), '#ecb84f')
    source.paste('#244858', (0, 0, 128, 160))
    source.paste('#784238', (256, 0, 384, 160))
    data = io.BytesIO(); source.save(data, format='PNG')
    asset = import_image(store, actor, data.getvalue(), 'image/png')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
           f'<image href="asset:{asset}" width="384" height="160"/></svg>')
    return store, actor, app, service, svg


def create(service, actor, svg='', key='create'):
    return service.command(actor, {'command': {'kind': 'create', 'brief': 'Три связанные карточки',
        'card_count': 3, 'card_width': 128, 'card_height': 160, 'svg': svg}, 'request_key': key})


def code(expected, fn):
    with pytest.raises(DomainError) as error:
        fn()
    assert error.value.code == expected


def pixels(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert('RGB')


def test_transparent_original_renders_over_background_across_seam(runtime):
    store, actor, app, service, _ = runtime
    original = Image.new('RGBA', (100, 60), (255, 255, 255, 0))
    original.paste((240, 45, 25, 255), (20, 15, 84, 45))
    exif = Image.Exif()
    exif[270] = 'Original private metadata'
    data = io.BytesIO()
    original.save(data, format='PNG', exif=exif)
    asset = import_image(store, actor, data.getvalue(), 'image/png')
    derivative, _, _ = app.read_asset(actor, asset)
    assert pixels(derivative).getpixel((2, 2)) == (255, 255, 255)

    rgba, mime, _ = service._composition_asset(actor, asset)
    assert mime == 'image/png'
    with Image.open(io.BytesIO(rgba)) as image:
        assert image.mode == 'RGBA' and 'exif' not in image.info
        assert image.getpixel((2, 2))[3] == 0

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
           '<rect width="384" height="160" fill="#173957"/>'
           f'<image href="asset:{asset}" x="90" y="20" width="100" height="60"/>'
           '</svg>')
    ident = create(service, actor, svg, key='transparent-cutout')['carousel_id']
    rendered = service.command(actor, {'command': {'kind': 'render', 'carousel_id': ident,
        'revision': 1, 'view': 'region', 'region': [90, 20, 100, 60]}})
    result = pixels(rendered.data)
    assert result.getpixel((2, 2)) == (23, 57, 87)  # transparent, not white
    assert result.getpixel((29, 30)) == (240, 45, 25)  # left of seam x=128
    assert result.getpixel((51, 30)) == (240, 45, 25)  # right of seam
    assert result.getpixel((98, 58)) == (23, 57, 87)
    assert pixels(app.read_asset(actor, asset)[0]).getpixel((2, 2)) == (255, 255, 255)
    assert len(service.command(actor, {'command': {'kind': 'export', 'carousel_id': ident,
        'revision': 1}, 'request_key': 'transparent-export'})['cards']) == 3


def test_background_fragment_exact_layers_and_private_asset(runtime):
    store, actor, app, service, _ = runtime
    svg = ('''<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">
      <defs><linearGradient id="ink"><stop stop-color="#d93628"/></linearGradient></defs>
      <g transform="translate(4 0)"><rect id="bg-pane" x="0" y="0" width="380" height="160"
        fill="#173957"/></g>
      <g id="text-zone"><rect x="120" y="20" width="70" height="100"
        fill="url(#ink)"/></g></svg>''')
    ident = create(service, actor, svg, key='fragment-scene')['carousel_id']
    with store.connection() as db:
        row = service._version(db, actor, ident, 1)
    master = pixels(service._render(actor, row))
    region = [110, 30, 80, 70]
    command = {'kind': 'render', 'carousel_id': ident, 'revision': 1,
               'view': 'region', 'region': region, 'scale': 1}
    exact = service.command(actor, {'command': command})
    assert exact.metadata['mime_type'] == 'image/png' and exact.metadata['reencoded'] is False
    assert exact.metadata['width'] == 80 and exact.metadata['height'] == 70
    assert exact.data.startswith(b'\x89PNG\r\n\x1a\n')
    assert ImageChops.difference(pixels(exact.data), master.crop((110, 30, 190, 100))).getbbox() is None

    only = service.command(actor, {'command': {**command,
        'layers': {'only': ['bg-pane']}, 'save_asset': True}})
    assert pixels(only.data).getpixel((30, 20)) == (23, 57, 87)
    assert pixels(only.data).getpixel((5, 20)) == (23, 57, 87)
    assert only.metadata['resource_uri'] == 'vibepublish://assets/' + only.metadata['asset_ref']
    saved, mime, _ = app.read_asset(actor, only.metadata['asset_ref'])
    assert mime == 'image/png'
    assert ImageChops.difference(pixels(saved), pixels(only.data)).getbbox() is None

    hide = service.command(actor, {'command': {**command,
        'layers': {'hide': ['text-zone']}}})
    assert pixels(hide.data).getpixel((30, 20)) == (23, 57, 87)
    assert pixels(exact.data).getpixel((30, 20)) == (217, 54, 40)
    assert pixels(service.command(actor, {'command': {**command,
        'layers': {'only': ['text-zone']}}}).data).getpixel((5, 20)) == (255, 255, 255)
    journal = service.command(actor, {'command': {'kind': 'get', 'scope': 'journal',
        'carousel_id': ident}})['journal']
    event = next(e for e in journal if e.get('save_asset'))
    assert event['revision'] == 1 and event['scale'] == 1
    assert event['region'] == region and event['layers'] == {'only': ['bg-pane']}
    assert event['asset_ref'] == only.metadata['asset_ref'] and event['duration_ms'] >= 0
    code('carousel_layer_not_found', lambda: service.command(actor, {'command': {
        **command, 'layers': {'only': ['nonexistent']}}}))


def test_background_fragment_rejects_oversized_exact_crop(runtime):
    _, actor, _, service, _ = runtime
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="2700" height="160"/>'
    ident = service.command(actor, {'command': {'kind': 'create', 'brief': 'Large canvas',
        'card_count': 3, 'card_width': 900, 'card_height': 160, 'svg': svg},
        'request_key': 'large-background'})['carousel_id']
    with pytest.raises(DomainError, match='split into smaller regions') as error:
        service.command(actor, {'command': {'kind': 'render', 'carousel_id': ident,
            'revision': 1, 'view': 'region', 'region': [0, 0, 2561, 160], 'scale': 1}})
    assert error.value.code == 'carousel_region_exact_limit'


def test_exact_large_opaque_fragment_saves_without_changing_pixels(runtime):
    store, actor, app, service, _ = runtime
    original = Image.frombytes('RGB', (2560, 2560), random.Random(117).randbytes(2560 * 2560 * 3))
    encoded = io.BytesIO()
    original.save(encoded, format='PNG')
    asset = import_image(store, actor, encoded.getvalue(), 'image/png')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="2560">'
           f'<image href="asset:{asset}" width="2560" height="2560"/></svg>')
    ident = service.command(actor, {'command': {'kind': 'create', 'brief': 'Exact background',
        'card_count': 3, 'card_width': 1280, 'card_height': 2560, 'svg': svg},
        'request_key': 'large-opaque-background'})['carousel_id']
    result = service.command(actor, {'command': {'kind': 'render', 'carousel_id': ident,
        'revision': 1, 'view': 'region', 'region': [0, 0, 2560, 2560],
        'scale': 1, 'save_asset': True}})
    assert result.metadata['mime_type'] == 'image/png' and result.metadata['reencoded'] is False
    with Image.open(io.BytesIO(result.data)) as fragment:
        assert fragment.mode == 'RGB' and fragment.size == original.size
        assert fragment.tobytes() == original.tobytes()
    saved, mime, _ = app.read_asset(actor, result.metadata['asset_ref'])
    assert mime == 'image/png' and pixels(saved).tobytes() == original.tobytes()


def test_reference_edit_renders_exact_seam_and_replayable_private_export(runtime):
    store, actor, app, service, svg = runtime
    bank = ReferenceBank(store)
    bank.root.mkdir()
    Image.new('RGB', (20, 20), '#f6ead4').save(bank.root / 'panel.png')
    (bank.root / 'catalog.json').write_text(json.dumps({
        'owner': {'tenant_id': actor.tenant_id, 'principal_id': actor.principal_id}, 'references': [{
        'id': 'E02', 'file': 'panel.png', 'title': 'Общая панель', 'tags': ['панель'],
        'look_for': 'Панель проходит через шов', 'transfer': 'Объединить соседние зоны',
        'source': {'slack_url': 'https://example.slack.com/archives/C1/p1', 'file_id': 'F1'},
        'use_note': 'Reference only'}]}))
    first = create(service, actor, svg)
    ident = first['carousel_id']
    assert first['private'] and first['generation_dispatch'] == 'not_sent'
    seen = bank.get(actor, 'E02')
    assert pixels(seen.data).getpixel((10, 10)) == (246, 234, 212)
    revised_svg = svg.replace('</svg>', '<rect x="108" y="30" width="40" height="100" fill="#f6ead4"/></svg>')
    args = {'command': {'kind': 'revise', 'carousel_id': ident, 'expected_revision': 1,
        'svg': revised_svg, 'note': 'Упростить переход 1|2',
        'reference_use': {'reference_id': 'E02', 'observation': 'Общая панель связывает зоны',
                          'change': 'Добавлена одна панель через шов 1|2'}}, 'request_key': 'use-E02'}
    second = service.command(actor, args)
    assert second['revision'] == 2
    assert service.command(actor, args)['operation_id'] == second['operation_id']
    compact = service.command(actor, {'command': {'kind': 'get', 'carousel_id': ident}})
    assert compact['journal'][0]['reference_use'] == args['command']['reference_use']
    assert compact['asset_refs'] and 'svg' not in compact
    original = service.command(actor, {'command': {'kind': 'get', 'carousel_id': ident,
                                                   'revision': 1, 'include_svg': True}})
    assert original['svg'] == svg and original['latest_revision'] == 2
    crop = service.command(actor, {'command': {'kind': 'render', 'carousel_id': ident,
        'revision': 2, 'view': 'region', 'region': [118, 35, 20, 90]}})
    assert crop.metadata['region'] == [118, 35, 20, 90]
    assert pixels(crop.data).getextrema() == ((246, 246), (234, 234), (212, 212))
    card = service.command(actor, {'command': {'kind': 'render', 'carousel_id': ident,
        'revision': 2, 'card': 2}})
    assert pixels(card.data).size == (128, 160)
    whole = service.command(actor, {'command': {'kind': 'render', 'carousel_id': ident,
        'revision': 2, 'view': 'region', 'region': [0, 0, 384, 160]}})
    export = {'command': {'kind': 'export', 'carousel_id': ident, 'revision': 2}, 'request_key': 'export-two'}
    result = service.command(actor, export)
    assert result['state'] == 'verified' and result['deliveries'] == [] and result['private']
    assert [card['index'] for card in result['cards']] == [1, 2, 3]
    joined = Image.new('RGB', (384, 160))
    for index, card in enumerate(result['cards']):
        raw, mime, sha = app.read_asset(actor, card['asset_ref'])
        assert mime == card['mime_type'] and sha == card['sha256']
        assert result['media'][index]['source']['id'] == card['asset_ref']
        joined.paste(pixels(raw), (index * 128, 0))
    assert joined.tobytes() == pixels(whole.data).tobytes()
    with store.connection() as db:
        before = db.execute('SELECT count(*) FROM assets').fetchone()[0]
        for table in ('attempts', 'publications', 'visual_jobs'):
            assert db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
    replay = service.command(actor, export)
    assert replay['operation_id'] == result['operation_id'] and replay['cards'] == result['cards']
    assert store.receipt(actor, result['operation_id'])['cards'] == result['cards']
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == before
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE carousel_versions SET brief=? WHERE id=?', ('overwrite', ident))


def test_brief_first_revision_fence_and_key_conflict(runtime):
    _, actor, _, service, svg = runtime
    first = create(service, actor)
    ident = first['carousel_id']
    assert not first['scene_ready']
    code('carousel_scene_missing', lambda: service.command(actor, {'command': {
        'kind': 'render', 'carousel_id': ident, 'revision': 1}}))
    change = {'command': {'kind': 'revise', 'carousel_id': ident,
                         'expected_revision': 1, 'svg': svg}, 'request_key': 'compose'}
    ready = service.command(actor, change)
    assert ready['revision'] == 2 and ready['scene_ready']
    code('carousel_revision_conflict', lambda: service.command(actor, {**change, 'request_key': 'stale'}))
    code('idempotency_conflict', lambda: create(service, actor, svg))
    code('carousel_request_key_required', lambda: service.command(actor, {'command': change['command']}))
    bad = {**change, 'command': {**change['command'], 'expected_revision': 2,
        'reference_use': {'reference_id': 'unknown', 'observation': 'claim', 'change': 'claim'}}, 'request_key': 'missing-bank'}
    code('carousel_reference_unavailable', lambda: service.command(actor, bad))


def test_render_journal_records_requested_historical_revision(runtime):
    _, actor, _, service, svg = runtime
    ident = create(service, actor, svg, key='historical-create')['carousel_id']
    updated = service.command(actor, {'command': {'kind': 'revise', 'carousel_id': ident,
        'expected_revision': 1, 'caption': 'Новая подпись'}, 'request_key': 'historical-revise'})
    assert updated['revision'] == 2
    service.command(actor, {'command': {'kind': 'render', 'carousel_id': ident,
        'revision': 1, 'card': 1}})
    entries = service.command(actor, {'command': {'kind': 'get',
        'scope': 'journal', 'carousel_id': ident}})['journal']
    render = next(entry for entry in entries if entry['kind'] == 'render')
    assert render['revision'] == 1
    assert render['view'] == 'card' and render['card'] == 1


@pytest.mark.asyncio
async def test_journal_pages_beyond_fifty_events_without_losing_order(runtime):
    store, actor, app, service, _ = runtime
    now = store.clock()
    store.clock = lambda: now  # Equal timestamps must preserve the ledger's row order.
    first = create(service, actor)
    ident = first['carousel_id']
    operation_ids = [first['operation_id']]
    for revision in range(1, 55):
        changed = service.command(actor, {'command': {'kind': 'revise', 'carousel_id': ident,
            'expected_revision': revision, 'note': f'Правка {revision}'},
            'request_key': f'journal-revise-{revision}'})
        operation_ids.append(changed['operation_id'])
    command = {'kind': 'get', 'scope': 'journal', 'carousel_id': ident}
    first_page = await app.call(actor, 'vibepublish_carousel', {'command': command})
    assert len(first_page['journal']) == 50
    assert first_page.get('offset') == 0 and first_page.get('next_offset') == 50
    last_page = await app.call(actor, 'vibepublish_carousel', {
        'command': {**command, 'offset': first_page['next_offset']}})
    assert 'error' not in last_page
    assert len(last_page['journal']) == 5
    assert last_page['offset'] == 50 and last_page['next_offset'] is None
    assert [entry['operation_id'] for entry in first_page['journal'] + last_page['journal']] == operation_ids[::-1]
    assert last_page['journal'][-1]['kind'] == 'create'
    story = await app.call(actor, 'vibepublish_carousel', {
        'command': {'kind': 'get', 'carousel_id': ident}})
    assert len(story['journal']) == 10 and 'next_offset' not in story


def test_private_scope_revocation_and_invalid_regions(runtime):
    store, actor, app, service, svg = runtime
    ident = create(service, actor, svg)['carousel_id']
    other = store.authenticate(store.create_principal('tenant', 'other', owner=True))
    get = {'command': {'kind': 'get', 'carousel_id': ident}}
    code('carousel_not_available', lambda: service.command(other, get))
    for region in ([0, 0, 0, 1], [-1, 0, 20, 20], [380, 0, 10, 20], [True, 0, 1, 1]):
        code('carousel_region_invalid', lambda: service.command(actor, {'command': {
            'kind': 'render', 'carousel_id': ident, 'revision': 1, 'view': 'region', 'region': region}}))
    with store.tx() as db:
        db.execute('UPDATE principals SET active=0 WHERE id=?', (actor.principal_id,))
    code('access_revoked', lambda: service.command(actor, get))
    code('access_revoked', lambda: create(service, actor, svg))


@pytest.mark.asyncio
async def test_real_application_validates_all_commands_and_status(runtime):
    store, actor, app, _, svg = runtime
    async def call(command, key=None):
        args = {'command': command, **({'request_key': key} if key else {})}
        result = await app.call(actor, 'vibepublish_carousel', args)
        assert 'error' not in (result if isinstance(result, dict) else result.metadata)
        return result
    created = await call({'kind': 'create', 'brief': 'История без готового рисунка',
        'card_count': 3, 'card_width': 128, 'card_height': 160}, 'app-create')
    ident = created['carousel_id']
    state = await call({'kind': 'get', 'carousel_id': ident, 'include_svg': True})
    assert not state['scene_ready'] and state['svg'] == ''
    revised = await call({'kind': 'revise', 'carousel_id': ident,
        'expected_revision': 1, 'svg': svg}, 'app-revise')
    image = await call({'kind': 'render', 'carousel_id': ident, 'revision': revised['revision'], 'card': 1})
    assert pixels(image.data).size == (128, 160)
    bank = ReferenceBank(store)
    bank.root.mkdir()
    Image.new('RGB', (24, 24), '#efdbbd').save(bank.root / 'panel.png')
    (bank.root / 'catalog.json').write_text(json.dumps({
        'owner': {'tenant_id': actor.tenant_id, 'principal_id': actor.principal_id}, 'references': [{
            'id': 'E02', 'file': 'panel.png', 'title': 'Панель', 'tags': ['панель'],
            'look_for': 'Одна панель', 'transfer': 'Повторить приём',
            'source': {'slack_url': 'https://example.slack.com/archives/C1/p1', 'file_id': 'F1'},
            'use_note': 'Reference only'}]}))
    library = await call({'kind': 'get', 'scope': 'library', 'carousel_id': ident,
                          'query': 'private-query-must-not-be-logged'})
    assert library['references'] == []
    original = await call({'kind': 'get', 'scope': 'reference', 'carousel_id': ident,
                           'reference_id': 'E02'})
    assert pixels(original.data).size == (24, 24)
    journal = await call({'kind': 'get', 'scope': 'journal', 'carousel_id': ident})
    kinds = [item['kind'] for item in journal['journal']]
    assert kinds[:2] == ['get', 'get'] and {'asset_import', 'render', 'create', 'revise'} <= set(kinds)
    assert all('at' in event and 'operation_id' in event for event in journal['journal'])
    assert all(isinstance(event['duration_ms'], int) and event['duration_ms'] >= 0
               for event in journal['journal'] if event['kind'] in {'render', 'get'})
    assert journal['journal'][0]['reference_id'] == 'E02'
    assert journal['journal'][1]['scope'] == 'library'
    assert not any('private-query-must-not-be-logged' in json.dumps(event)
                   for event in journal['journal'])
    assert [item['view'] for item in journal['journal'] if item['kind'] == 'render'] == ['card']
    imports = [item for item in journal['journal'] if item['kind'] == 'asset_import']
    assert len(imports) == 1 and imports[0]['asset_ref'] in journal['asset_refs']
    assert 'imported_at' in imports[0]
    assert len((await call({'kind': 'get', 'scope': 'journal', 'carousel_id': ident,
                            'limit': 3}))['journal']) == 3
    assert (await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'get', 'scope': 'journal', 'carousel_id': ident, 'limit': 51}}))['error']['code'] == 'invalid_input'
    exported = await call({'kind': 'export', 'carousel_id': ident, 'revision': 2}, 'app-export')
    timings = (await call({'kind': 'get', 'scope': 'journal', 'carousel_id': ident}))['journal']
    assert {'create', 'revise', 'render', 'export', 'get'} <= {
        entry['kind'] for entry in timings if isinstance(entry.get('duration_ms'), int)}
    status = await app.call(actor, 'vibepublish_status', {'ids': [exported['operation_id']]})
    assert status['receipts'][0]['cards'] == exported['cards']
    with store.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 12


def test_saved_story_and_export_survive_cache_expiry_and_asset_reclamation(runtime):
    store, actor, app, service, svg = runtime
    ident = create(service, actor, svg)['carousel_id']
    scene = service.command(actor, {'command': {'kind': 'get', 'carousel_id': ident}})
    export_args = {'command': {'kind': 'export', 'carousel_id': ident, 'revision': 1},
                   'request_key': 'durable-export'}
    exported = service.command(actor, export_args)
    retained = set(scene['asset_refs']) | {card['asset_ref'] for card in exported['cards']}
    render_args = {'command': {'kind': 'render', 'carousel_id': ident, 'revision': 1,
                              'view': 'region', 'region': [0, 0, 384, 160]}}
    before = pixels(service.command(actor, render_args).data).tobytes()
    unused_bytes = io.BytesIO()
    Image.new('RGB', (16, 16), 'black').save(unused_bytes, format='PNG')
    unused = import_image(store, actor, unused_bytes.getvalue(), 'image/png')
    started = store.clock()
    with store.tx() as db:
        # Local FK-valid download-cache fixtures, with no grants or provider calls.
        db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?)',
            ('pub_cache_fixture', actor.tenant_id, actor.principal_id, 1, 'media_store', started))
        db.executemany('INSERT INTO media_store_assets VALUES(?,?,?,?)',
            [(ref, 'pub_cache_fixture', 'download_cache', started + 3600) for ref in retained | {unused}])
    store.clock = lambda: started + 15 * 86400
    with store.tx() as db:
        rows = retired_asset_rows(db, store.clock())
        reasons = {row['id']: row['reason'] for row in rows}
        assert all(reasons[ref] == 'saved_carousel' for ref in retained)
        assert reasons[unused] == 'reclaim'
        app._purge_media_store_assets(db)
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (unused,)).fetchone() is None
        reclaim_asset_bytes(db, rows)
        remaining = {row[0] for row in db.execute('SELECT id FROM assets')}
        assert retained <= remaining
    assert pixels(service.command(actor, render_args).data).tobytes() == before
    assert service.command(actor, export_args)['cards'] == exported['cards']
    for card in exported['cards']:
        raw, _, sha = app.read_asset(actor, card['asset_ref'])
        assert pixels(raw).size == (128, 160) and sha == card['sha256']
