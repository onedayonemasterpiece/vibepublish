"""Real seam geometry, private image resolution, typography and SVG boundaries."""
import hashlib
import io

import pytest
from PIL import Image, ImageChops

from social_operations.carousel_compositor import render_svg, slice_cards, validate_svg
from social_operations.domain import DomainError


SIZE = {'card_count': 3, 'card_width': 200, 'card_height': 200}


def svg(body, attrs=''):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="200" {attrs}>{body}</svg>'


def no_asset(ident):
    pytest.fail(f'Unexpected asset resolution: {ident}')


def render(source, resolver=no_asset):
    return render_svg(source, read_asset=resolver, **SIZE)


def image(data):
    return Image.open(io.BytesIO(data)).convert('RGB')


def test_one_image_and_panel_cross_seam_without_independent_rescaling():
    original = Image.new('RGB', (80, 80), '#064f79')
    for y in range(80):
        for x in range(40, 80):
            original.putpixel((x, y), (230, 160, 50))
    out = io.BytesIO()
    original.save(out, 'PNG')
    data = out.getvalue()
    reads = []

    def resolve(ident):
        reads.append(ident)
        return data, 'image/png', hashlib.sha256(data).hexdigest()

    master = render(svg('''
      <defs><clipPath id="panel"><rect x="150" y="20" width="100" height="140" rx="20"/></clipPath></defs>
      <image href="asset:photo_1" x="150" y="20" width="100" height="140"
             preserveAspectRatio="none" clip-path="url(#panel)"/>
      <image href="vibepublish://assets/photo_1" x="450" y="20" width="80" height="80"/>
    '''), resolve)
    cards = slice_cards(master, **SIZE)
    assert reads == ['photo_1']
    assert len(cards) == 3 and all(image(card).size == (200, 200) for card in cards)
    joined = Image.new('RGB', (600, 200))
    for index, card in enumerate(cards):
        joined.paste(image(card), (index * 200, 0))
    assert ImageChops.difference(image(master), joined).getbbox() is None
    assert image(cards[0]).getpixel((170, 80)) == (6, 79, 121)
    assert image(cards[1]).getpixel((30, 80)) == (230, 160, 50)
    assert image(master).getpixel((150, 20)) == (255, 255, 255)  # rounded corner


def test_only_preserves_defs_and_ancestor_transform_while_hide_removes_subtree():
    source = svg('''
      <defs><linearGradient id="gradient"><stop stop-color="#114477"/></linearGradient></defs>
      <g transform="translate(10 0)"><g id="background">
        <rect width="500" height="200" fill="url(#gradient)"/>
      </g></g>
      <g id="foreground"><rect x="15" y="30" width="50" height="50" fill="#ff0000"/></g>
    ''')
    only = image(render_svg(source, read_asset=no_asset, layers={'only': ['background']}, **SIZE))
    hide = image(render_svg(source, read_asset=no_asset, layers={'hide': ['foreground']}, **SIZE))
    assert only.getpixel((25, 40)) == (17, 68, 119)
    assert only.getpixel((5, 40)) == (255, 255, 255)
    assert hide.getpixel((25, 40)) == (17, 68, 119)
    assert image(render(source)).getpixel((25, 40)) == (255, 0, 0)


def test_only_rejects_removed_use_dependency_and_accepts_a_definition():
    shape = '<rect id="shape" width="40" height="40" fill="#ff0000"/>'
    copy = '<use id="background-copy" href="#shape" x="100"/>'
    source = svg(shape + copy)
    assert image(render(source)).getpixel((120, 20)) == (255, 0, 0)
    with pytest.raises(DomainError) as error:
        render_svg(source, read_asset=no_asset, layers={'only': ['background-copy']}, **SIZE)
    assert error.value.code == 'carousel_layer_dependency'

    defined = svg('<defs>' + shape + '</defs>' + copy)
    selected = image(render_svg(defined, read_asset=no_asset,
                                layers={'only': ['background-copy']}, **SIZE))
    assert selected.getpixel((120, 20)) == (255, 0, 0)
    assert selected.getpixel((20, 20)) == (255, 255, 255)


def test_root_layer_selection_keeps_all_or_hides_all():
    source = svg('<rect width="600" height="200" fill="#114477"/>', 'id="canvas"')
    only = render_svg(source, read_asset=no_asset, layers={'only': ['canvas']}, **SIZE)
    assert image(only).tobytes() == image(render(source)).tobytes()
    hidden = render_svg(source, read_asset=no_asset, layers={'hide': ['canvas']}, **SIZE)
    assert image(hidden).getextrema() == ((255, 255),) * 3


def test_cyrillic_and_explicit_line_positions_render_with_supported_font():
    source = svg('<text x="18" y="70" font-family="Montserrat" font-weight="700" font-size="38">'
                 'Памятник<tspan x="18" y="130">дружбе</tspan></text>')
    pixels = image(render(source))
    assert ImageChops.difference(pixels.crop((0, 20, 300, 80)), Image.new('RGB', (300, 60), 'white')).getbbox()
    assert ImageChops.difference(pixels.crop((0, 85, 300, 140)), Image.new('RGB', (300, 55), 'white')).getbbox()
    assert pixels.getpixel((599, 199)) == (255, 255, 255)
    with pytest.raises(DomainError, match='Fonts'):
        render(source.replace('Montserrat', 'Some Remote Font'))


@pytest.mark.parametrize('body', [
    '<image href="file:///etc/passwd"/>',
    '<image href="https://example.invalid/file.png"/>',
    '<image href="//example.invalid/file.png"/>',
    '<image href="data:image/svg+xml;base64,PHN2Zy8+"/>',
    '<rect fill="url(https://example.invalid/x)"/>',
    '<style>@import "https://example.invalid/style.css";</style>',
    '<rect onclick="alert(1)"/>',
    '<foreignObject/>', '<script/>', '<use href="https://example.invalid/use.svg#id"/>',
])
def test_unsafe_source_rejected_before_renderer(body):
    with pytest.raises(DomainError) as exc:
        render(svg(body))
    assert exc.value.code == 'carousel_svg_unsafe'


def test_private_asset_access_and_actual_raster_type_are_required():
    def revoked(_ident):
        raise DomainError('access_revoked')
    with pytest.raises(DomainError) as exc:
        render(svg('<image href="asset:private"/>'), revoked)
    assert exc.value.code == 'access_revoked'
    source = svg('<image id="private" href="asset:private"/>'
                 '<rect id="background" width="600" height="200"/>', 'id="canvas"')
    for layers in ({'only': ['background']}, {'hide': ['canvas']}):
        with pytest.raises(DomainError) as exc:
            render_svg(source, read_asset=revoked, layers=layers, **SIZE)
        assert exc.value.code == 'access_revoked'
    with pytest.raises(DomainError) as exc:
        render(svg('<image href="asset:private"/>'), lambda _: (b'<svg/>', 'image/png', 'fake'))
    assert exc.value.code == 'carousel_asset_invalid'


def test_definition_types_dimensions_complexity_and_entities_are_bounded():
    cases = [
        (svg('<rect fill="url(#missing)"/>'), 'carousel_svg_invalid'),
        (svg('<rect width="1e999"/>'), 'carousel_svg_limit'),
        (svg('<rect width="NaN"/>'), 'carousel_svg_limit'),
        (svg('<mask id="m" width="100001"/>'), 'carousel_svg_limit'),
        (svg('<g>' * 25 + '</g>' * 25), 'carousel_svg_limit'),
        (svg('<rect/>' * 1201), 'carousel_svg_limit'),
        (svg('', 'viewBox="0 0 600 600"'), 'carousel_dimensions_invalid'),
        ('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + svg('&x;'), 'carousel_svg_invalid'),
    ]
    for source, expected in cases:
        with pytest.raises(DomainError) as exc:
            validate_svg(source, **SIZE)
        assert exc.value.code == expected
    with pytest.raises(DomainError):
        render_svg(svg(''), card_count=10, card_width=2560, card_height=2560, read_asset=no_asset)
    with pytest.raises(DomainError):
        slice_cards(render(svg('')), card_count=3, card_width=201, card_height=200)


def test_validation_can_preserve_private_refs_without_reading_pixels():
    source = validate_svg(svg('<image href="asset:photo_1"/>'), **SIZE)
    assert b'asset:photo_1' in source and b'data:' not in source
    assert b'width="600"' in source


def test_large_reused_asset_stays_out_of_svg_and_fetches_only_from_validated_map(monkeypatch):
    import resvg_py
    out = io.BytesIO()
    Image.new('RGB', (1536, 1536), '#123456').save(out, 'PNG', compress_level=0)
    data = out.getvalue()
    assert len(data) * 7 * 4 / 3 > 44 * 1024 * 1024  # The former repeated base64 limit.
    source = '<svg>' + ''.join(f'<image href="asset:photo" x="{i*128}" width="128" height="128"/>'
                              for i in range(7)) + '</svg>'
    size = {'card_count': 7, 'card_width': 128, 'card_height': 128}
    reads = []
    def resolve(ident):
        reads.append(ident)
        return data, 'image/png', hashlib.sha256(data).hexdigest()
    normalized = validate_svg(source, read_asset=resolve, **size)
    assert len(normalized) < 2000 and b'data:' not in normalized and reads == ['photo']
    reads.clear()
    convert = resvg_py.svg_to_bytes
    def guarded(**kwargs):
        assert kwargs['skip_system_fonts'] is True
        assert len(kwargs['font_files']) == 10
        assert kwargs['svg_string'].count(';base64,') == 1
        assert 'asset:photo' not in kwargs['svg_string']
        return convert(**kwargs)
    monkeypatch.setattr(resvg_py, 'svg_to_bytes', guarded)
    monkeypatch.setattr('social_operations.carousel_compositor.MAX_COMPOSITION_ASSET_BYTES', len(data))
    pixels = image(render_svg(source, read_asset=resolve, **size))
    assert reads == ['photo'] and pixels.size == (896, 128)
    assert all(max(abs(a - b) for a, b in zip(pixels.getpixel((i*128+64, 64)), (18, 52, 86))) <= 4
               for i in range(7))  # opaque rasters may be JPEG-embedded
    with pytest.raises(DomainError) as exc:
        validate_svg(source.replace('asset:photo', 'asset:second', 1), read_asset=resolve, **size)
    assert exc.value.code == 'carousel_svg_limit'  # Unique source bytes remain bounded.


def test_large_oswald_cyrillic_title_and_kerning_phrase():
    oswald = svg('<text x="10" y="95" font-family="Oswald" font-weight="700" font-size="58">'
                 'КАЛИНИНГРАД 1977</text>')
    pixels = image(render(oswald))
    assert ImageChops.difference(pixels, Image.new('RGB', pixels.size, 'white')).getbbox()
    grotesk = svg('<text x="15" y="100" font-family="Montserrat" font-size="58" font-weight="700">'
                  'AVATAR ТАТА</text>')
    pixels = image(render(grotesk))
    assert ImageChops.difference(pixels, Image.new('RGB', pixels.size, 'white')).getbbox()


def test_style_class_use_filter_pattern_paint_order_italic_and_default_mask():
    source = svg("""
      <defs>
        <rect id="shape" width="80" height="70" rx="9"/>
        <pattern id="pat" width="12" height="12" patternUnits="userSpaceOnUse">
          <rect width="12" height="12" fill="#11aabb"/>
          <circle cx="6" cy="6" r="3" fill="#aa1155"/>
        </pattern>
        <filter id="blur"><feGaussianBlur stdDeviation="1"/></filter>
        <mask id="mask"><rect width="100%" height="100%" fill="white"/></mask>
      </defs>
      <style>.accent {fill: #e6ad44; paint-order: stroke fill;}</style>
      <rect x="10" y="10" width="140" height="100" fill="url(#pat)" mask="url(#mask)"/>
      <use href="#shape" class="accent" x="180" y="15" filter="url(#blur)"/>
      <text x="20" y="180" font-family="Montserrat" font-style="italic"
            style="font-weight:550;fill:#123456" font-size="32">КАЛИНИНГРАД</text>
    """)
    normalized = validate_svg(source, **SIZE)
    assert b'patternUnits' in normalized and b'paint-order' in normalized
    pixels = image(render(source))
    assert ImageChops.difference(pixels, Image.new('RGB', pixels.size, 'white')).getbbox()
