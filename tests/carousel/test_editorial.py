"""Primary material survives addressed edits, replay, concurrency and retention."""
import io

import pytest
from PIL import Image

from social_operations.assets import import_image, reclaim_asset_bytes, retired_asset_rows
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store


@pytest.fixture
def runtime(tmp_path):
    now = [1800000000.0]
    store = Store(tmp_path / 'editorial.sqlite', clock=lambda: now[0])
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    return store, actor, Application(store), now


def editorial(raw='Автор: «Это наблюдение, не доказанная причина».'):
    return {'materials': [{'id': 'm1', 'text': raw, 'source': 'owner message'}],
            'points': [{'id': 'p1', 'text': 'Автор предполагает связь', 'material_ids': ['m1'],
                        'modality': 'hypothesis'},
                       {'id': 'p2', 'text': 'Отдельное наблюдение', 'material_ids': ['m1'],
                        'modality': 'observation'}],
            'narrative': 'Цельный рассказ с причинной связью.',
            'cards': [{'id': 'c1', 'text': 'Версия автора', 'point_ids': ['p1']},
                      {'id': 'c2', 'text': 'Следующий эпизод', 'point_ids': []}]}


def call(app, actor, command, key=None):
    return app.carousels.command(actor, {'command': command, **({'request_key': key} if key else {})})


def get(app, actor, ident, revision=None):
    return call(app, actor, {'kind': 'get', 'scope': 'story', 'carousel_id': ident,
                            **({'revision': revision} if revision else {})})


def revise(app, actor, ident, revision, changes, key='patch', **extra):
    return call(app, actor, {'kind': 'revise', 'carousel_id': ident, 'expected_revision': revision,
                            'story_changes': changes, **extra}, key)


def counts(store):
    with store.connection() as db:
        return tuple(db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                     for table in ('carousel_versions', 'operations', 'request_keys'))


@pytest.mark.asyncio
async def test_public_typed_patch_keeps_long_raw_modality_and_explicit_continuation(runtime):
    store, actor, app, _ = runtime
    raw = 'Автор дословно: «наблюдение»\n' * 700
    story = editorial(raw)
    args = {'command': {'kind': 'create', 'story': story}, 'request_key': 'structured-create'}
    created = await app.call(actor, 'vibepublish_carousel', args)
    assert 'error' not in created, created
    ident = created['carousel_id']
    result = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'revise', 'carousel_id': ident, 'expected_revision': 1,
        'story_changes': [{'kind': 'card_patch', 'id': 'c1', 'text': 'Уточнённая строка'},
                          {'kind': 'material_add', 'material': {
                              'id': 'm2', 'continuation_of': 'm1', 'text': 'Продолжение без усечения'}}]},
        'request_key': 'card-patch'})
    assert 'error' not in result, result
    current = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'get', 'scope': 'story', 'carousel_id': ident}})
    assert current['story']['materials'][0]['text'] == raw
    assert current['story']['materials'][1]['continuation_of'] == 'm1'
    assert current['story']['points'] == story['points']
    assert current['story']['narrative'] == story['narrative']
    assert current['story']['cards'][0] == {**story['cards'][0], 'text': 'Уточнённая строка'}
    assert current['story']['cards'][1] == story['cards'][1]
    assert current['declared_unlinked_point_ids'] == ['p2']  # Declaration, not a semantic verdict.
    assert current['editorial_format'] == 'structured'
    assert get(app, actor, ident, 1)['story'] == story


def test_correction_supersedes_without_rewriting_old_version_and_explicit_delete(runtime):
    store, actor, app, _ = runtime
    story = editorial()
    ident = call(app, actor, {'kind': 'create', 'story': story}, 'create')['carousel_id']
    revise(app, actor, ident, 1, [
        {'kind': 'material_add', 'material': {'id': 'm3', 'text': 'Уточнение владельца', 'supersedes': 'm1'}},
        {'kind': 'point_patch', 'id': 'p1', 'material_ids': ['m3'], 'modality': 'position'},
        {'kind': 'card_patch', 'id': 'c3', 'text': 'Финал', 'point_ids': ['p1']},
        {'kind': 'cards_order', 'ids': ['c3', 'c1', 'c2']},
        {'kind': 'narrative_set', 'text': 'Новая связная версия.'}])
    current = get(app, actor, ident)['story']
    assert current['materials'][0] == story['materials'][0]
    assert current['materials'][1]['supersedes'] == 'm1'
    assert current['points'][0]['text'] == story['points'][0]['text']
    assert get(app, actor, ident, 1)['story'] == story
    revise(app, actor, ident, 2, [{'kind': 'card_remove', 'id': 'c3'},
                                {'kind': 'point_remove', 'id': 'p2'}], 'delete')
    assert len(get(app, actor, ident)['story']['points']) == 1
    before = counts(store)
    for changes, error in [
        ([{'kind': 'material_add', 'material': {'id': 'm1', 'text': 'overwrite'}}], 'carousel_material_immutable'),
        ([{'kind': 'material_remove', 'id': 'm1'}], 'carousel_story_reference'),
        ([{'kind': 'point_remove', 'id': 'p1'}], 'carousel_story_reference'),
        ([{'kind': 'point_patch', 'id': 'new', 'text': 'missing modality'}], 'carousel_story_invalid'),
    ]:
        with pytest.raises(DomainError) as failure:
            revise(app, actor, ident, 3, changes, 'invalid-' + error)
        assert failure.value.code == error
        assert counts(store) == before


def test_legacy_svg_only_migration_conflict_and_old_successful_replay(runtime):
    store, actor, app, _ = runtime
    create_args = {'kind': 'create', 'brief': 'Полный старый исходник'}
    created = call(app, actor, create_args, 'legacy')
    ident = created['carousel_id']
    legacy_write = {'kind': 'revise', 'carousel_id': ident, 'expected_revision': 1,
                    'brief': 'Уточнённый старый исходник'}
    legacy_receipt = call(app, actor, legacy_write, 'legacy-write')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="7560" height="1350"/>'
    call(app, actor, {'kind': 'revise', 'carousel_id': ident, 'expected_revision': 2,
                     'svg': svg}, 'svg-only')
    assert get(app, actor, ident)['brief'] == legacy_write['brief']
    assert get(app, actor, ident)['editorial_format'] == 'legacy'
    call(app, actor, {'kind': 'revise', 'carousel_id': ident, 'expected_revision': 3,
                     'story': editorial()}, 'migrate')
    current = get(app, actor, ident)
    assert current['brief_historical'] and current['brief'] == legacy_write['brief']
    assert call(app, actor, create_args, 'legacy')['operation_id'] == created['operation_id']
    replay = call(app, actor, legacy_write, 'legacy-write')
    assert (replay['operation_id'], replay['revision']) == (legacy_receipt['operation_id'], 2)
    before = counts(store)
    with pytest.raises(DomainError, match='Structured story') as failure:
        call(app, actor, {**legacy_write, 'expected_revision': 4}, 'new-legacy-write')
    assert failure.value.code == 'carousel_editorial_conflict' and counts(store) == before
    call(app, actor, {'kind': 'revise', 'carousel_id': ident, 'expected_revision': 4,
                     'svg': svg}, 'structured-svg-only')
    assert get(app, actor, ident)['story'] == current['story']


def test_stale_cas_and_racing_prepare_do_not_commit_editorial_or_svg(runtime, monkeypatch):
    store, actor, app, _ = runtime
    ident = call(app, actor, {'kind': 'create', 'story': editorial()}, 'create')['carousel_id']
    original = app.carousels._prepare
    def concurrent(actor, command, previous):
        prepared = original(actor, command, previous)
        monkeypatch.setattr(app.carousels, '_prepare', original)
        call(app, actor, {'kind': 'revise', 'carousel_id': ident, 'expected_revision': 1,
                         'note': 'Concurrent accepted revision'}, 'concurrent')
        return prepared
    monkeypatch.setattr(app.carousels, '_prepare', concurrent)
    with pytest.raises(DomainError) as failure:
        revise(app, actor, ident, 1, [{'kind': 'card_patch', 'id': 'c1', 'text': 'Must not commit'}])
    assert failure.value.code == 'carousel_revision_conflict'
    assert get(app, actor, ident)['revision'] == 2
    assert get(app, actor, ident)['story'] == editorial()
    before = counts(store)
    with pytest.raises(DomainError) as failure:
        revise(app, actor, ident, 1, [{'kind': 'narrative_set', 'text': 'Stale'}], 'stale')
    assert failure.value.code == 'carousel_revision_conflict' and counts(store) == before


def image_asset(store, actor, color):
    data = io.BytesIO()
    Image.new('RGBA', (30, 40), color).save(data, 'PNG')
    return import_image(store, actor, data.getvalue(), 'image/png')


def test_material_outside_svg_and_its_original_survive_cleanup_and_reopen(runtime):
    store, actor, app, now = runtime
    asset = image_asset(store, actor, (255, 0, 0, 100))
    replacement = image_asset(store, actor, (0, 255, 0, 100))
    unrelated = image_asset(store, actor, (0, 0, 255, 100))
    story = editorial()
    story['materials'][0]['asset_ref'] = asset
    created = call(app, actor, {'kind': 'create', 'story': story}, 'material')
    ident = created['carousel_id']
    original_bytes = app.read_asset(actor, asset)[0]
    with store.connection() as db:
        original_id = db.execute('SELECT source.id FROM assets derived JOIN assets source '
            'ON source.sha256=derived.source_sha256 WHERE derived.id=? AND source.id!=derived.id',
            (asset,)).fetchone()[0]
    original_raw = app.read_asset(actor, original_id)[0]
    revise(app, actor, ident, 1, [
        {'kind': 'material_add', 'material': {'id': 'm2', 'asset_ref': replacement, 'supersedes': 'm1'}},
        {'kind': 'point_patch', 'id': 'p1', 'material_ids': ['m2']},
        {'kind': 'card_patch', 'id': 'c1', 'text': 'Уточнение'}])
    # Remove both versions from the current payload: only immutable history can hold them.
    revise(app, actor, ident, 2, [
        {'kind': 'material_add', 'material': {'id': 'm3', 'text': 'Новый самостоятельный источник'}},
        {'kind': 'point_patch', 'id': 'p1', 'material_ids': ['m3']},
        {'kind': 'point_patch', 'id': 'p2', 'material_ids': ['m3']},
        {'kind': 'material_remove', 'id': 'm2'},
        {'kind': 'material_remove', 'id': 'm1'}], 'historical-only')
    assert asset not in get(app, actor, ident)['asset_refs']
    assert replacement not in get(app, actor, ident)['asset_refs']
    now[0] += 15 * 86400
    with store.tx() as db:
        rows = retired_asset_rows(db, now[0])
        assert {r['id']: r['reason'] for r in rows}[unrelated] == 'reclaim'
        assert {r['id']: r['reason'] for r in rows}[asset] == 'saved_carousel'
        reclaim_asset_bytes(db, rows)
    reopened = Application(Store(store.path, clock=store.clock))
    assert reopened.read_asset(actor, asset)[0] == original_bytes
    assert reopened.read_asset(actor, original_id)[0] == original_raw
    assert reopened.read_asset(actor, replacement)[0]
    assert get(reopened, actor, ident, 1)['story'] == story
    assert get(reopened, actor, ident, 2)['story']['materials'][1]['supersedes'] == 'm1'
    assert get(reopened, actor, ident)['story']['materials'] == [{'id': 'm3', 'text': 'Новый самостоятельный источник'}]
    # Material references are dependencies, never automatically rendered SVG images.
    assert call(reopened, actor, {'kind': 'get', 'scope': 'components', 'carousel_id': ident}).metadata['components'] == []


@pytest.mark.parametrize('tenant,principal', [('tenant', 'other'), ('foreign', 'foreign_owner')])
def test_material_asset_never_expands_owner_acl(runtime, tenant, principal):
    store, actor, app, _ = runtime
    other = store.authenticate(store.create_principal(tenant, principal, owner=True))
    foreign_asset = image_asset(store, other, (10, 20, 30, 100))
    story = editorial()
    story['materials'][0]['asset_ref'] = foreign_asset
    before = counts(store)
    with pytest.raises(DomainError) as failure:
        call(app, actor, {'kind': 'create', 'story': story}, 'foreign')
    assert failure.value.code == 'asset_not_available' and counts(store) == before


def test_schema12_upgrade_keeps_legacy_rows_and_adds_nullable_story(runtime):
    store, actor, app, _ = runtime
    ident = call(app, actor, {'kind': 'create', 'brief': 'Stored before schema13'}, 'legacy')['carousel_id']
    with store.connection() as db:
        db.execute('ALTER TABLE carousel_versions DROP COLUMN story_json')
        db.execute('PRAGMA user_version=12')
    reopened = Application(Store(store.path))
    assert get(reopened, actor, ident)['brief'] == 'Stored before schema13'
    assert get(reopened, actor, ident)['editorial_format'] == 'legacy'
    with reopened.store.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 13
        assert db.execute('SELECT story_json FROM carousel_versions').fetchone()[0] is None


def test_cleanup_between_preparation_and_commit_rejects_without_revision(runtime, monkeypatch):
    store, actor, app, now = runtime
    asset = image_asset(store, actor, (200, 100, 0, 100))
    ident = call(app, actor, {'kind': 'create', 'story': editorial()}, 'create')['carousel_id']
    before = counts(store)
    original = app.carousels._prepare
    def cleanup(actor, command, previous):
        prepared = original(actor, command, previous)
        now[0] += 15 * 86400
        with store.tx() as db:
            reclaim_asset_bytes(db, retired_asset_rows(db, now[0]))
        return prepared
    monkeypatch.setattr(app.carousels, '_prepare', cleanup)
    with pytest.raises(DomainError) as failure:
        revise(app, actor, ident, 1, [{'kind': 'material_add', 'material': {
            'id': 'm2', 'asset_ref': asset}}])
    assert failure.value.code == 'asset_not_available'
    assert counts(store) == before


def test_material_id_reuse_requires_explicit_removal_and_old_revision_stays_exact(runtime):
    _, actor, app, _ = runtime
    story = editorial()
    story['materials'].append({'id': 'unused', 'text': 'Исторические слова'})
    ident = call(app, actor, {'kind': 'create', 'story': story}, 'create')['carousel_id']
    revise(app, actor, ident, 1, [{'kind': 'material_remove', 'id': 'unused'},
        {'kind': 'material_add', 'material': {'id': 'unused', 'text': 'Явная новая запись'}}])
    assert get(app, actor, ident, 1)['story']['materials'][-1]['text'] == 'Исторические слова'
    assert get(app, actor, ident)['story']['materials'][-1]['text'] == 'Явная новая запись'


def test_missing_and_unsupported_material_assets_leave_no_durable_effect(runtime):
    store, actor, app, _ = runtime
    asset = image_asset(store, actor, (200, 100, 200, 100))
    # An existing media asset may have a supported non-image MIME elsewhere.
    # Use a real immutable video row, not a mocked authorization/read method.
    with store.tx() as db:
        row = db.execute('SELECT * FROM assets WHERE id=?', (asset,)).fetchone()
        db.execute('INSERT INTO assets(id,tenant_id,principal_id,bytes,mime,sha256,source_sha256,width,height,created) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('video_material', actor.tenant_id, actor.principal_id, row['bytes'], 'video/mp4',
                    row['sha256'], row['source_sha256'], row['width'], row['height'], row['created']))
    before = counts(store)
    for ref, code in [('asset_missing', 'asset_not_available'),
                      ('video_material', 'carousel_material_asset_unsupported')]:
        story = editorial()
        story['materials'][0]['asset_ref'] = ref
        with pytest.raises(DomainError) as failure:
            call(app, actor, {'kind': 'create', 'story': story}, ref)
        assert failure.value.code == code and counts(store) == before


@pytest.mark.asyncio
async def test_empty_editorial_artifacts_recommend_source_work_without_blocking_export(runtime):
    _, actor, app, _ = runtime
    empty = {'materials': [], 'points': [], 'narrative': '', 'cards': []}
    first = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'create', 'story': empty, 'card_count': 3, 'card_width': 128, 'card_height': 160,
        'svg': '<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160"/>'},
        'request_key': 'empty-editorial'})
    assert 'error' not in first, first
    assert first['work_context']['recommendation']['get']['topic'] == 'steps/s01'
    assert first['work_context']['recommendation']['suggested_focus'] == 'source_material'
    exported = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'export', 'carousel_id': first['carousel_id'], 'revision': 1},
        'request_key': 'empty-export'})
    assert 'error' not in exported and len(exported['cards']) == 3
    assert exported['work_context']['recommendation']['suggested_focus'] == 'source_material'
