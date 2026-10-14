import hashlib
import io
import json

import pytest
from PIL import Image, ImageOps

from social_operations.assets import import_image, verify_image
from tests.providers.test_native_adapters import asset
from tests.visuals import test_visual_service
from tests.visuals.test_visual_service import call, select_command


@pytest.fixture
def runtime(tmp_path):
    return test_visual_service.runtime.__wrapped__(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('format,size', [('post_4_5', (1080, 1350)), ('story_9_16', (1080, 1920)), ('original', (1200, 800))])
async def test_source_frame_has_private_immutable_lineage_exact_format_and_no_executor_or_publish(runtime, format, size):
    store, actor, app, worker, executor, provider, *_ = runtime
    source_size = {'post_4_5': (400, 500), 'story_9_16': (360, 640), 'original': (1200, 800)}[format]
    stream = io.BytesIO(); Image.new('RGB', source_size, '#206040').save(stream, format='PNG')
    raw = stream.getvalue()
    source = import_image(store, actor, raw, 'image/png')
    with store.connection() as db:
        original = [tuple(r) for r in db.execute('SELECT * FROM assets')]
    args = {'command': {'kind': 'frame_source', 'source': {'source': {'kind': 'asset', 'id': source}},
        'copy': {'title': 'Полный исходный кадр', 'body': 'Датированное явное утверждение.'}, 'format': format,
        'layout': {'text_box': [.05, .02, .9, .25]}},
        'request_key': 'owner-source-frame'}
    ready = await call(app, actor, 'visual', args)
    assert ready['state'] == 'needs_selection' and ready['generation_dispatch'] == 'not_sent'
    assert executor.calls == [] and provider.count('effect') == 0
    assert not await worker.run_once()
    candidate = ready['candidates'][0]
    assert (candidate['width'], candidate['height']) == size and candidate['requires_review']
    with store.connection() as db:
        row = db.execute('SELECT * FROM visual_candidates WHERE id=?', (candidate['id'],)).fetchone()
        recipe, provenance = json.loads(row['recipe']), json.loads(row['provenance'])
        assert recipe['art_fit'] == 'contain' and recipe['canvas_fit'] == 'fixed'
        assert recipe['copy'] == args['command']['copy']
        source_bytes = db.execute('SELECT bytes FROM assets WHERE id=?', (source,)).fetchone()[0]
        assert row['art_ref'] == source and row['art_sha256'] == hashlib.sha256(source_bytes).hexdigest()
        assert recipe['art_box'] == [0, 0, size[0], size[1]]
        assert provenance['actual_model'] is None and provenance['generation_dispatch'] == 'not_sent'
        assert provenance['original_source_ref'] == source
        assert [tuple(db.execute('SELECT * FROM assets WHERE id=?', (r[0],)).fetchone()) for r in original] == original
    replayed = await call(app, actor, 'visual', args)
    assert replayed['operation_id'] == ready['operation_id']
    assert replayed['candidates'] == ready['candidates']
    selected = await call(app, actor, 'visual', {'command': select_command(ready), 'request_key': 'select-source-frame'})
    assert selected['selected_asset_ref'] == candidate['asset_ref']
    assert selected['selected_sha256'] == candidate['sha256']
    assert executor.calls == [] and provider.count('effect') == 0
    recomposed = await call(app, actor, 'visual', {'command': {
        'kind': 'recompose', 'job_id': ready['visual_job_id'], 'candidate_id': candidate['id'],
        'expected_visual_revision': selected['visual_revision'], 'expected_sha256': candidate['sha256'],
        'format': format}, 'request_key': 'owner-recompose-source-frame'})
    with store.connection() as db:
        recipe = json.loads(db.execute('SELECT recipe FROM visual_candidates WHERE job_id=?',
            (recomposed['visual_job_id'],)).fetchone()[0])
        assert recipe['source_layout'] == args['command']['layout']
        assert recipe['art_box'][3] == size[1] and recipe['art_fit'] == 'contain'
    assert executor.calls == [] and provider.count('effect') == 0


@pytest.mark.asyncio
async def test_source_frame_rejects_foreign_source_empty_or_overflowing_copy_and_missing_key(runtime):
    store, actor, app, _, executor, provider, *_ = runtime
    other = store.authenticate(store.create_principal('other', 'foreign', owner=True))
    foreign = import_image(store, other, asset(1).data, 'image/png')
    source = import_image(store, actor, asset(1).data, 'image/png')
    base = {'kind': 'frame_source', 'source': {'source': {'kind': 'asset', 'id': source}},
        'copy': {'title': 'Явный текст'}, 'layout': {'text_box': [.05, .02, .9, .15]}}
    for command, key in [({**base, 'source': {'source': {'kind': 'asset', 'id': foreign}}}, 'foreign'),
            ({**base, 'copy': {}}, 'empty'), ({**base, 'copy': {'body': 'Длинный текст. ' * 70}}, 'overflow'), (base, None)]:
        result = await app.call(actor, 'vibepublish_visual', {'command': command, **({'request_key': key} if key else {})})
        assert 'error' in result
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM visual_candidates').fetchone()[0] == 0
    assert executor.calls == [] and provider.count('effect') == 0


@pytest.mark.parametrize('orientation', range(1, 9))
def test_sanitized_ingress_applies_all_exif_orientations_without_mutating_original(orientation):
    image = Image.new('RGB', (24, 40))
    for x in range(24):
        for y in range(40):
            image.putpixel((x, y), (x*10, y*6, (x+y)*3))
    exif = Image.Exif(); exif[274] = orientation
    output = io.BytesIO(); image.save(output, format='JPEG', quality=95, exif=exif)
    raw = output.getvalue()
    with Image.open(io.BytesIO(raw)) as decoded:
        expected = ImageOps.exif_transpose(decoded).convert('RGB')
    verified = verify_image(raw, 'image/jpeg')
    assert verified.original == raw
    with Image.open(io.BytesIO(verified.data)) as derivative:
        assert derivative.size == expected.size
        assert derivative.tobytes() == expected.tobytes()
        assert not derivative.getexif()


@pytest.mark.parametrize('format', ['post_4_5', 'story_9_16'])
def test_source_frame_requires_real_crop_and_never_adds_contain_fields(format):
    from social_operations.compositor import render
    from social_operations.domain import DomainError
    stream = io.BytesIO(); Image.new('RGB', (600, 400)).save(stream, format='PNG')
    with pytest.raises(DomainError) as exc:
        render(stream.getvalue(), {'title': 'Photo'}, format, source_layout={'text_box': [.05, .02, .9, .25]})
    assert exc.value.code == 'source_frame_requires_true_crop'


def test_original_composition_preserves_aspect_and_every_source_pixel_outside_annotation():
    from social_operations.compositor import render
    from PIL import ImageChops
    source = Image.new('RGB', (1200, 800))
    for x in range(1200):
        for y in range(800):
            source.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    stream = io.BytesIO(); source.save(stream, format='PNG')
    result = render(stream.getvalue(), {'title': 'Photo'}, 'original', source_layout={'text_box': [.05, .02, .9, .25]})
    with Image.open(io.BytesIO(result.png)) as rendered:
        assert rendered.size == source.size
        assert ImageChops.difference(rendered.convert('RGB').crop((0, 250, 1200, 800)), source.crop((0, 250, 1200, 800))).getbbox() is None
    assert json.loads(result.recipe_json)['art_content_box'] == [0, 0, 1200, 800]


def test_contrast_plate_covers_actual_text_instead_of_unused_layout_height():
    from social_operations.compositor import render
    stream = io.BytesIO(); Image.new('RGB', (1080, 1440), '#206040').save(stream, format='PNG')
    result = render(stream.getvalue(), {'title': 'Short title'}, 'original',
        source_layout={'text_box': [.1, .05, .8, .4], 'backplate_opacity': .3})
    recipe = json.loads(result.recipe_json)
    assert recipe['backplate_box'][3] < recipe['safe_box'][3] / 3
    with Image.open(io.BytesIO(result.png)) as image:
        assert image.getpixel((300, 500))[:3] == (32, 96, 64)
    assert recipe['copy']['title'] == 'Short title'
