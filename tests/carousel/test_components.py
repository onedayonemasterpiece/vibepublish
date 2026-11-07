"""Actual component pixels and honest placement metadata through the private MCP path."""
import base64
import io
import json

import pytest
from PIL import Image

from social_operations.assets import import_image
from social_operations.service import Application
from social_operations.storage import Store


def scene(body):
    return '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="256">' + body + '</svg>'


async def create(app, actor, body, key='create'):
    result = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'create', 'brief': 'See the actual source component',
        'card_count': 3, 'card_width': 240, 'card_height': 256, 'svg': scene(body)},
        'request_key': key})
    assert 'error' not in result, result
    return result['carousel_id']


def source(store, actor):
    data = io.BytesIO()
    Image.new('RGB', (30, 40), 'red').save(data, 'PNG')
    return import_image(store, actor, data.getvalue(), 'image/png')


@pytest.fixture
def runtime(tmp_path):
    store = Store(tmp_path / 'components.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    return store, actor, Application(store)


@pytest.mark.asyncio
@pytest.mark.parametrize(('attrs', 'parent', 'expected'), [
    ('x="5" y="10" width="30" height="40"', 'translate(100 20) scale(2)', (110, 40, 60, 80)),
    ('x="5px" y="10" width="30px" height="40"', '', (5, 10, 30, 40)),
    ('x="1in" y="0.25in" width="6pt" height="3pc"', '', (96, 24, 8, 48)),
    ('x="25%" y="25%" width="50%" height="50%"', '', (180, 64, 360, 128)),
    ('x="5" y="10" width="30" height="40"', 'matrix(-1 0 0 1 100 20)', (65, 30, 30, 40)),
    ('x="5" y="10" width="30" height="40"', 'rotate(90)', (-50, 5, 40, 30)),
    ('x="5" y="10" width="30" height="40"', 'skewX(45)', (15, 10, 70, 40)),
])
async def test_component_bounds_are_canvas_placements(runtime, attrs, parent, expected):
    store, actor, app = runtime
    asset = source(store, actor)
    story = await create(app, actor, f'<g transform="{parent}"><image id="cutout" class="foreground" '
                         f'href="asset:{asset}" {attrs}/></g>')
    result = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'get', 'scope': 'components', 'carousel_id': story, 'revision': 1}})
    component, = result.metadata['components']
    assert component['element_ids'] == ['cutout'] and component['classes'] == ['foreground']
    assert tuple(component[key] for key in ('x', 'y', 'w', 'h')) == pytest.approx(expected)
    assert tuple(component['placements'][0][key] for key in ('x', 'y', 'w', 'h')) == pytest.approx(expected)
    assert component['preview']['image_index'] == 0 and len(result.images) == 1


@pytest.mark.asyncio
async def test_xlink_image_source_is_visible_in_components(runtime):
    store, actor, app = runtime
    asset = source(store, actor)
    story = await create(app, actor,
        '<image xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'xlink:href="asset:{asset}" x="5px" y="10" width="30" height="40"/>')
    result = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'get', 'scope': 'components', 'carousel_id': story, 'revision': 1}})
    component, = result.metadata['components']
    assert component['asset_ref'] == asset and len(result.images) == 1
    assert tuple(component[key] for key in ('x', 'y', 'w', 'h')) == (5, 10, 30, 40)


@pytest.mark.asyncio
@pytest.mark.parametrize('unknown', [
    '<image id="unknown" href="asset:{asset}" x="1em" width="30" height="40"/>',
    '<svg width="100" height="100"><image id="unknown" href="asset:{asset}" width="50%" height="50%"/></svg>',
    '<image id="unknown" style="TrAnSfOrM:translate(50px,20px)" href="asset:{asset}" width="30" height="40"/>',
    '<image id="unknown" transform-origin="center" transform-box="fill-box" transform="rotate(45)" href="asset:{asset}" width="30" height="40"/>',
    '<defs><image id="unknown" href="asset:{asset}" width="30" height="40"/></defs><use href="#unknown" x="100"/>',
    '<image id="unknown" href="asset:{asset}" width="30" height="40"/>'
    '<use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#unknown" x="100"/>',
])
async def test_unknown_bounds_keep_images_and_known_placements(runtime, unknown):
    store, actor, app = runtime
    asset = source(store, actor)
    story = await create(app, actor,
        f'<image id="known" href="asset:{asset}" x="10" y="20" width="30" height="40"/>'
        + unknown.format(asset=asset))
    result = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'get', 'scope': 'components', 'carousel_id': story, 'revision': 1}})
    component, = result.metadata['components']
    assert 'bounds_unavailable' in component and 'x' not in component
    known, unknown = component['placements']
    assert (known['x'], known['y'], known['w'], known['h']) == (10, 20, 30, 40)
    assert unknown['bounds_unavailable'] and 'local' in unknown and 'transforms' in unknown
    assert result.images[0].metadata['mime_type'] == 'image/webp'


@pytest.mark.asyncio
async def test_component_pages_read_only_the_requested_assets(runtime, monkeypatch):
    store, actor, app = runtime
    assets = []
    for index in range(7):
        data = io.BytesIO()
        Image.new('RGB', (30, 40), (index * 30, 0, 0)).save(data, 'PNG')
        assets.append(import_image(store, actor, data.getvalue(), 'image/png'))
    story = await create(app, actor, ''.join(
        f'<image href="asset:{asset}" x="{index * 30}" width="30" height="40"/>'
        for index, asset in enumerate(assets)))
    reads, resolve = [], app.carousels._composition_asset

    def counted(actor, asset):
        reads.append(asset)
        return resolve(actor, asset)

    monkeypatch.setattr(app.carousels, '_composition_asset', counted)
    for offset, expected, following in ((0, assets[:5], 5), (5, assets[5:], None), (7, [], None)):
        reads.clear()
        result = await app.call(actor, 'vibepublish_carousel', {'command': {
            'kind': 'get', 'scope': 'components', 'carousel_id': story, 'revision': 1, 'offset': offset}})
        page = result.metadata
        assert page['total'] == 7 and page['offset'] == offset and page['next_offset'] == following
        assert [component['asset_ref'] for component in page['components']] == expected
        assert [component['preview']['image_index'] for component in page['components']] == list(range(len(expected)))
        assert len(result.images) == len(expected) and reads == expected


@pytest.mark.asyncio
async def test_component_thumbnails_are_images_in_actual_mcp_transport():
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from tests.runtime.test_transport import TransportTests

    transport = TransportTests()
    await transport.asyncSetUp()
    try:
        asset = source(transport.store, transport.actor)
        story = await create(Application(transport.store), transport.actor,
                             f'<image href="asset:{asset}" width="30" height="40"/>')
        async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + transport.token},
                                     trust_env=False) as http:
            async with streamable_http_client(transport.base + '/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.call_tool('vibepublish_carousel', {'command': {
                        'kind': 'get', 'scope': 'components', 'carousel_id': story, 'revision': 1}})
                    assert not response.isError, response
                    component, = response.structuredContent['components']
                    images = [item for item in response.content if item.type == 'image']
                    assert len(images) == 1 and component['preview']['image_index'] == 0
                    assert images[0].mimeType == 'image/webp'
                    with Image.open(io.BytesIO(base64.b64decode(images[0].data))) as rendered:
                        assert rendered.size == (30, 40) and rendered.convert('RGB').getpixel((15, 20))[0] > 200
                    assert 'base64' not in json.dumps(response.structuredContent)
                    assert all('base64' not in item.text for item in response.content if item.type == 'text')
    finally:
        await transport.cleanup_server()
