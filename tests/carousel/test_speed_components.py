"""One lossless source embedding preserves opaque pixels and alpha on every instance."""
import base64
import hashlib
import io
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from social_operations.carousel_compositor import render_svg


@pytest.mark.parametrize('mode', ['RGB', 'RGBA'])
def test_repeated_source_is_embedded_once_without_resizing_or_reencoding(mode, monkeypatch):
    from social_operations import svg_raster

    source = Image.new(mode, (320, 240), (18, 52, 86, 0) if mode == 'RGBA' else (18, 52, 86))
    source.paste((200, 0, 0, 255) if mode == 'RGBA' else (200, 0, 0), (80, 60, 240, 180))
    output = io.BytesIO()
    source.save(output, 'PNG')
    data = output.getvalue()
    reads = []

    def resolve(ident):
        reads.append(ident)
        return data, 'image/png', hashlib.sha256(data).hexdigest()

    rasterize = svg_raster.svg_to_bytes

    def inspect_embedding(**kwargs):
        images = [node.get('href') for node in ET.fromstring(kwargs['svg_string']).iter()
                  if node.get('href', '').startswith('data:')]
        assert len(images) == 1 and images[0].startswith('data:image/png;base64,')
        assert base64.b64decode(images[0].split(',', 1)[1]) == data
        return rasterize(**kwargs)

    monkeypatch.setattr(svg_raster, 'svg_to_bytes', inspect_embedding)
    png = render_svg('<svg width="384" height="160">'
        '<rect width="384" height="160" fill="#173957"/>'
        '<image href="asset:photo" x="90" y="20" width="80" height="60"/>'
        '<image href="asset:photo" x="256" y="20" width="80" height="60"/>'
        '</svg>', card_count=3, card_width=128, card_height=160, read_asset=resolve)
    assert reads == ['photo']
    with Image.open(io.BytesIO(png)) as rendered:
        pixels = rendered.convert('RGB')
        assert pixels.getpixel((92, 22)) == ((23, 57, 87) if mode == 'RGBA' else (18, 52, 86))
        assert pixels.getpixel((130, 50)) == pixels.getpixel((296, 50)) == (200, 0, 0)
