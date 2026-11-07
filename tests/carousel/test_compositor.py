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


def test_one_image_and_panel_cross_seam_without_independent_rescaling(monkeypatch):
    # A private asset is fetched once even when repeated. Cairo's URL opener must
    # never be used, including for legitimate private image resources.
    monkeypatch.setattr('cairosvg.url.urlopen', lambda *a, **k: pytest.fail('Network access'))
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


def test_cyrillic_and_explicit_line_positions_render_with_supported_font():
    source = svg('<text x="18" y="70" font-family="DejaVu Sans" font-weight="700" font-size="38">'
                 'Памятник<tspan x="18" y="130">дружбе</tspan></text>')
    pixels = image(render(source))
    assert ImageChops.difference(pixels.crop((0, 20, 300, 80)), Image.new('RGB', (300, 60), 'white')).getbbox()
    assert ImageChops.difference(pixels.crop((0, 85, 300, 140)), Image.new('RGB', (300, 55), 'white')).getbbox()
    assert pixels.getpixel((599, 199)) == (255, 255, 255)
    with pytest.raises(DomainError, match='DejaVu'):
        render(source.replace('DejaVu Sans', 'Some Remote Font'))


@pytest.mark.parametrize('body', [
    '<image href="file:///etc/passwd"/>',
    '<image href="https://example.invalid/file.png"/>',
    '<image href="//example.invalid/file.png"/>',
    '<image href="data:image/svg+xml;base64,PHN2Zy8+"/>',
    '<rect fill="url(https://example.invalid/x)"/>',
    '<style>@import "https://example.invalid/style.css";</style>',
    '<rect style="fill:red"/>', '<rect onclick="alert(1)"/>',
    '<foreignObject/>', '<script/>', '<use href="#loop" id="loop"/>',
    '<filter id="huge"/>',
    '<defs><clipPath id="loop"><rect clip-path="url(#loop)"/></clipPath></defs>',
])
def test_unsafe_source_rejected_before_renderer(monkeypatch, body):
    monkeypatch.setattr('cairosvg.surface.PNGSurface.convert', lambda **kw: pytest.fail('Unsafe render'))
    with pytest.raises(DomainError) as exc:
        render(svg(body))
    assert exc.value.code == 'carousel_svg_unsafe'


def test_private_asset_access_and_actual_raster_type_are_required():
    def revoked(_ident):
        raise DomainError('access_revoked')
    with pytest.raises(DomainError) as exc:
        render(svg('<image href="asset:private"/>'), revoked)
    assert exc.value.code == 'access_revoked'
    with pytest.raises(DomainError) as exc:
        render(svg('<image href="asset:private"/>'), lambda _: (b'<svg/>', 'image/png', 'fake'))
    assert exc.value.code == 'carousel_asset_invalid'


def test_definition_types_dimensions_complexity_and_entities_are_bounded():
    cases = [
        (svg('<rect id="r" fill="url(#r)"/>'), 'carousel_svg_invalid'),
        (svg('<rect width="1e999"/>'), 'carousel_svg_limit'),
        (svg('<rect width="NaN"/>'), 'carousel_svg_limit'),
        (svg('<mask id="m" maskUnits="userSpaceOnUse" width="100000"/>'), 'carousel_svg_limit'),
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
    from cairosvg.surface import PNGSurface
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
    convert = PNGSurface.convert
    def guarded(**kwargs):
        for forbidden in ('file:///private/file.png', 'https://example.invalid/x',
                          'data:image/png;base64,eA==', 'asset:unvalidated'):
            with pytest.raises(DomainError):
                kwargs['url_fetcher'](forbidden, 'image/*')
        return convert(**kwargs)
    monkeypatch.setattr(PNGSurface, 'convert', guarded)
    monkeypatch.setattr('social_operations.carousel_compositor.MAX_COMPOSITION_ASSET_BYTES', len(data))
    pixels = image(render_svg(source, read_asset=resolve, **size))
    assert reads == ['photo'] and pixels.size == (896, 128)
    assert all(pixels.getpixel((i*128+64, 64)) == (18, 52, 86) for i in range(7))
    with pytest.raises(DomainError) as exc:
        validate_svg(source.replace('asset:photo', 'asset:second', 1), read_asset=resolve, **size)
    assert exc.value.code == 'carousel_svg_limit'  # Unique source bytes remain bounded.
