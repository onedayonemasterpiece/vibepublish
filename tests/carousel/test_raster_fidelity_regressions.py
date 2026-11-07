"""Source detail survives SVG instances and nonuniform image viewports."""
import hashlib
import io

import pytest
from PIL import Image

from social_operations.carousel_compositor import render_svg


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
def test_raster_detail_survives_actual_svg_placement(case):
    if case == 'scaled_use':
        data = stripes((240, 240), vertical=True)
        body = ('<defs><image id="tile" href="asset:photo" width="24" height="24"/></defs>'
                '<use href="#tile" transform="scale(10)"/>')
    else:
        data = stripes((2400, 240), vertical=False)
        alignment = 'none' if case == 'none' else 'xMidYMid slice'
        body = ('<image href="asset:photo" width="240" height="240" '
                f'preserveAspectRatio="{alignment}"/>')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="720" height="256">'
           + body + '</svg>')
    png = render_svg(svg, card_count=3, card_width=240, card_height=256,
        read_asset=lambda _: (data, 'image/png', hashlib.sha256(data).hexdigest()))
    with Image.open(io.BytesIO(png)) as image:
        image = image.convert('L')
        values = [image.getpixel((i, 100) if case == 'scaled_use' else (100, i))
                  for i in range(16, 224)]
    assert min(values) < 40 and max(values) > 215, (min(values), max(values))
