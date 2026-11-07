"""Regression coverage for raster sampling, component geometry and MCP images."""
import hashlib
import io

import pytest
from PIL import Image

from social_operations.assets import import_image
from social_operations.carousel_compositor import render_svg
from social_operations.service import Application
from social_operations.storage import Store


def svg(body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="720" height="256">'
            + body + '</svg>')


def stripes(size, *, vertical):
    image = Image.new('RGB', size)
    for position in range(size[0] if vertical else size[1]):
        value = 255 if (position // 4) % 2 else 0
        box = ((position, 0, position + 1, size[1]) if vertical
               else (0, position, size[0], position + 1))
        image.paste((value, value, value), box)
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


@pytest.mark.parametrize('case', ['scaled_use', 'none', 'slice'])
def test_downsampling_preserves_detail_at_actual_painted_size(case):
    """Large instances/crops must retain visible stripes; no JPEG byte equality."""
    if case == 'scaled_use':
        data = stripes((240, 240), vertical=True)
        body = ('<defs><image id="tile" href="asset:photo" width="24" height="24"/></defs>'
                '<use href="#tile" transform="scale(10)"/>')
    else:
        data = stripes((2400, 240), vertical=False)
        alignment = 'none' if case == 'none' else 'xMidYMid slice'
        body = ('<image href="asset:photo" width="240" height="240" '
                f'preserveAspectRatio="{alignment}"/>')
    png = render_svg(svg(body), card_count=3, card_width=240, card_height=256,
        read_asset=lambda _: (data, 'image/png', hashlib.sha256(data).hexdigest()))
    with Image.open(io.BytesIO(png)) as image:
        image = image.convert('L')
        values = [image.getpixel((i, 100) if case == 'scaled_use' else (100, i))
                  for i in range(16, 224)]
    assert min(values) < 40 and max(values) > 215, (min(values), max(values))


@pytest.mark.asyncio
@pytest.mark.parametrize(('attrs', 'wrapper', 'expected'), [
    ('x="5" y="10" width="30" height="40"',
     'transform="translate(100 20) scale(2)"', (110, 40, 60, 80)),
    ('x="5px" y="10" width="30px" height="40"', '', (5, 10, 30, 40)),
])
async def test_component_bounds_are_canvas_coordinates_and_valid_svg_units(tmp_path, attrs, wrapper, expected):
    store = Store(tmp_path / 'components.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    app = Application(store)
    source = io.BytesIO()
    Image.new('RGB', (30, 40), 'red').save(source, 'PNG')
    asset = import_image(store, actor, source.getvalue(), 'image/png')
    created = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'create', 'brief': 'Geometry of an existing component',
        'card_count': 3, 'card_width': 240, 'card_height': 256,
        'svg': svg(f'<g {wrapper}><image id="cutout" class="foreground" '
                   f'href="asset:{asset}" {attrs}/></g>')}, 'request_key': 'create'})
    assert 'error' not in created, created
    result = await app.call(actor, 'vibepublish_carousel', {'command': {
        'kind': 'get', 'scope': 'components', 'carousel_id': created['carousel_id'], 'revision': 1}})
    assert 'error' not in result, result
    component, = result['components']
    assert component['element_ids'] == ['cutout'] and component['classes'] == ['foreground']
    assert tuple(component[key] for key in ('x', 'y', 'w', 'h')) == expected


@pytest.mark.asyncio
async def test_component_thumbnails_are_images_in_actual_mcp_transport():
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from tests.runtime.test_transport import TransportTests

    transport = TransportTests()
    await transport.asyncSetUp()
    try:
        source = io.BytesIO()
        Image.new('RGB', (30, 40), 'red').save(source, 'PNG')
        asset = import_image(transport.store, transport.actor, source.getvalue(), 'image/png')
        app = Application(transport.store)
        created = await app.call(transport.actor, 'vibepublish_carousel', {'command': {
            'kind': 'create', 'brief': 'Look at the actual component',
            'card_count': 3, 'card_width': 240, 'card_height': 256,
            'svg': svg(f'<image href="asset:{asset}" width="30" height="40"/>')},
            'request_key': 'mcp-image'})
        async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + transport.token},
                                     trust_env=False) as http:
            async with streamable_http_client(transport.base + '/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.call_tool('vibepublish_carousel', {'command': {
                        'kind': 'get', 'scope': 'components',
                        'carousel_id': created['carousel_id'], 'revision': 1}})
                    assert not response.isError, response
                    assert len(response.structuredContent['components']) == 1
                    assert any(item.type == 'image' for item in response.content), [item.type for item in response.content]
    finally:
        await transport.cleanup_server()
