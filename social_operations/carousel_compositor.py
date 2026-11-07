"""Private SVG carousel composition with bounded, local-only resources.

The model authors SVG geometry and explicit text lines. The application resolves
asset IDs with its existing ACL; this module never opens a model-supplied URL.
"""
from __future__ import annotations

import io
import math
import re
import warnings
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException
from fontTools.ttLib import TTFont
from PIL import Image, UnidentifiedImageError

from .domain import DomainError

MAX_SVG_BYTES = 256 * 1024
MAX_COMPOSITION_ASSET_BYTES = 44 * 1024 * 1024
FONTS = ('DejaVu Sans', 'DejaVu Serif', 'DejaVu Sans Mono')
_FONT_FILES = dict(zip(FONTS, ('DejaVuSans', 'DejaVuSerif', 'DejaVuSansMono')))
_SVG = 'http://www.w3.org/2000/svg'
_XLINK = 'http://www.w3.org/1999/xlink'
_NUMBER = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?')
_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,127}')
_ASSET = re.compile(r'(?:asset:|vibepublish://assets/)([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})')
_PAINT = re.compile(r'url\(\s*([\'"]?)#(?P<id>[A-Za-z_][A-Za-z0-9_.-]{0,127})\1\s*\)')
_GLOBAL = set(('id transform fill fill-opacity fill-rule stroke stroke-width '
               'stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray '
               'stroke-dashoffset stroke-opacity opacity clip-path clip-rule mask '
               'color font-family font-size font-style font-weight text-anchor '
               'dominant-baseline letter-spacing').split())
_ATTRS = {
    'svg': {'width', 'height', 'viewBox'}, 'g': set(), 'defs': set(),
    'rect': {'x', 'y', 'width', 'height', 'rx', 'ry'},
    'circle': {'cx', 'cy', 'r'}, 'ellipse': {'cx', 'cy', 'rx', 'ry'},
    'line': {'x1', 'y1', 'x2', 'y2'}, 'path': {'d'},
    'polygon': {'points'}, 'polyline': {'points'},
    'image': {'x', 'y', 'width', 'height', 'href', 'preserveAspectRatio'},
    'text': {'x', 'y', 'dx', 'dy', 'rotate'}, 'tspan': {'x', 'y', 'dx', 'dy', 'rotate'},
    'clipPath': {'clipPathUnits'},
    'mask': {'x', 'y', 'width', 'height', 'maskUnits', 'maskContentUnits'},
    'linearGradient': {'x1', 'y1', 'x2', 'y2', 'gradientUnits', 'gradientTransform', 'spreadMethod'},
    'radialGradient': {'cx', 'cy', 'r', 'fx', 'fy', 'gradientUnits', 'gradientTransform', 'spreadMethod'},
    'stop': {'offset', 'stop-color', 'stop-opacity'}, 'title': set(), 'desc': set(),
}
_NUMERIC = set(('x y dx dy x1 y1 x2 y2 cx cy r rx ry fx fy width height d points '
                'transform gradientTransform font-size letter-spacing stroke-width '
                'stroke-miterlimit stroke-dasharray stroke-dashoffset rotate').split())
_DEFINITIONS = {'clipPath', 'mask', 'linearGradient', 'radialGradient'}


def _dimensions(card_count, card_width, card_height):
    if (any(type(v) is not int for v in (card_count, card_width, card_height))
            or not 3 <= card_count <= 10
            or not 128 <= card_width <= 2560 or not 128 <= card_height <= 2560
            or card_count * card_width * card_height > 20_000_000):
        raise DomainError('carousel_dimensions_invalid')
    return card_count * card_width, card_height


@lru_cache(maxsize=6)
def _font_chars(family, bold):
    name = _FONT_FILES[family] + ('-Bold' if bold else '') + '.ttf'
    path = Path('/usr/share/fonts/truetype/dejavu') / name
    if not path.is_file():
        raise DomainError('carousel_font_not_available', 'Install the documented DejaVu font package', 'contact_owner')
    with TTFont(path) as font:
        return frozenset(font.getBestCmap())


def _image_bytes(ident, read_asset):
    data, mime, _sha = read_asset(ident)
    if mime not in {'image/png', 'image/jpeg', 'image/webp'} or len(data) > 20 * 1024 * 1024:
        raise DomainError('carousel_asset_invalid')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if (Image.MIME.get(image.format) != mime or image.width * image.height > 25_000_000
                        or getattr(image, 'n_frames', 1) != 1):
                    raise DomainError('carousel_asset_invalid')
                image.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise DomainError('carousel_asset_invalid') from exc
    return data


def validate_svg(svg, *, card_count, card_width, card_height, read_asset=None) -> bytes:
    """Validate without rendering; optionally resolve ACL-checked private assets.

    Source always retains canonical asset: links, never repeated inline bytes.
    A resolver validates each unique image once, outside a write transaction.
    """
    width, height = _dimensions(card_count, card_width, card_height)
    try:
        size = len(svg.encode('utf-8')) if isinstance(svg, str) else 0
    except UnicodeError as exc:
        raise DomainError('carousel_svg_invalid', 'SVG must contain valid Unicode') from exc
    if not 1 <= size <= MAX_SVG_BYTES:
        raise DomainError('carousel_svg_limit', 'SVG must be a UTF-8 string of at most 256 KiB')
    try:
        root = fromstring(svg, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ET.ParseError, DefusedXmlException, UnicodeError, LookupError, ValueError) as exc:
        raise DomainError('carousel_svg_invalid', 'SVG must be valid XML without DTDs or entities') from exc
    if root.tag not in {'svg', '{' + _SVG + '}svg'}:
        raise DomainError('carousel_svg_invalid', 'An SVG root is required')
    for key, expected in (('width', width), ('height', height)):
        value = root.get(key, str(expected))
        if not re.fullmatch(r'\d+(?:\.0+)?(?:px)?', value) or float(value.removesuffix('px')) != expected:
            raise DomainError('carousel_dimensions_invalid', 'SVG dimensions must match the card windows')
        root.set(key, str(expected))
    if 'viewBox' in root.attrib:
        try:
            values = [float(v) for v in re.split(r'[\s,]+', root.get('viewBox').strip())]
        except ValueError as exc:
            raise DomainError('carousel_dimensions_invalid') from exc
        if values != [0, 0, width, height]:
            raise DomainError('carousel_dimensions_invalid', 'Use viewBox="0 0 canvas_width card_height"')
    root.set('viewBox', f'0 0 {width} {height}')
    root.set('font-family', root.get('font-family', FONTS[0]))
    ids, references, images = {}, [], {}
    stack = [(root, 0, False, FONTS[0], False)]
    count = text_count = asset_bytes = 0
    while stack:
        node, depth, in_definition, family, bold = stack.pop()
        count += 1
        if count > 1200 or depth > 24:
            raise DomainError('carousel_svg_limit', 'SVG is too complex')
        tag = node.tag.removeprefix('{' + _SVG + '}')
        if tag not in _ATTRS or tag == 'svg' and node is not root:
            raise DomainError('carousel_svg_unsafe', 'Use supported SVG shapes, text, images and definitions')
        node.tag = '{' + _SVG + '}' + tag
        attrs = {}
        for raw_key, value in node.attrib.items():
            key = 'href' if raw_key == '{' + _XLINK + '}href' else raw_key
            if key == '{http://www.w3.org/XML/1998/namespace}space' and value in {'preserve', 'default'}:
                attrs[key] = value
                continue
            if key not in _GLOBAL | _ATTRS[tag] or key in attrs:
                raise DomainError('carousel_svg_unsafe', 'Use SVG presentation attributes; CSS, events and external resources are forbidden')
            if len(value) > 32_768 or ('url' in value.lower() and not _PAINT.fullmatch(value)):
                raise DomainError('carousel_svg_unsafe', 'Only local definition references are allowed')
            if key in _NUMERIC and (re.search(r'\b(?:nan|inf(?:inity)?)\b', value, re.I)
                                    or any(not math.isfinite(float(n)) or abs(float(n)) > 100_000
                                           for n in _NUMBER.findall(value))):
                raise DomainError('carousel_svg_limit', 'SVG coordinates are out of bounds')
            if key == 'font-size' and (not re.fullmatch(r'\d+(?:\.\d+)?(?:px)?', value)
                                       or not 1 <= float(value.removesuffix('px')) <= 2560):
                raise DomainError('carousel_svg_limit', 'Use a font size from 1 to 2560 pixels')
            ref = _PAINT.fullmatch(value)
            if ref:
                expected = {'fill': {'linearGradient', 'radialGradient'}, 'stroke': {'linearGradient', 'radialGradient'},
                            'clip-path': {'clipPath'}, 'mask': {'mask'}}.get(key)
                if not expected or in_definition or tag in _DEFINITIONS:
                    raise DomainError('carousel_svg_unsafe', 'Recursive or unsupported definition references are forbidden')
                references.append((ref['id'], expected))
            attrs[key] = value
        node.attrib.clear()
        node.attrib.update(attrs)
        if 'id' in attrs:
            if not _ID.fullmatch(attrs['id']) or attrs['id'] in ids:
                raise DomainError('carousel_svg_invalid', 'SVG IDs must be unique')
            ids[attrs['id']] = tag
        family = attrs.get('font-family', family).strip('"\'')
        if family not in FONTS or attrs.get('font-style', 'normal') != 'normal':
            raise DomainError('carousel_font_not_available', 'Use DejaVu Sans, DejaVu Serif or DejaVu Sans Mono, normal style')
        weight = attrs.get('font-weight', '700' if bold else '400')
        if weight not in {'normal', 'bold', '400', '700'}:
            raise DomainError('carousel_font_not_available', 'Use font-weight 400 or 700')
        bold = weight in {'bold', '700'}
        text = (node.text or '') + ''.join(child.tail or '' for child in node)
        text_count += len(text)
        if text_count > 16_000:
            raise DomainError('carousel_svg_limit', 'SVG contains too much text')
        if tag in {'text', 'tspan'} and any(ord(c) not in _font_chars(family, bold) for c in text if not c.isspace()):
            raise DomainError('carousel_glyph_not_available', 'A text character is not covered by the selected font')
        if tag == 'mask':
            if (attrs.get('maskUnits') != 'userSpaceOnUse'
                    or attrs.get('maskContentUnits', 'userSpaceOnUse') != 'userSpaceOnUse'):
                raise DomainError('carousel_svg_invalid', 'Masks require userSpaceOnUse units')
            for key, bound in (('width', width), ('height', height)):
                value = attrs.get(key, str(bound))
                if not re.fullmatch(r'\d+(?:\.\d+)?', value) or not 0 < float(value) <= bound:
                    raise DomainError('carousel_svg_limit', 'Mask dimensions must fit the canvas')
                node.set(key, value)
        if tag == 'image':
            match = _ASSET.fullmatch(attrs.get('href', ''))
            if not match:
                raise DomainError('carousel_svg_unsafe', 'Images require an authorized asset:ID reference')
            node.set('href', 'asset:' + match[1])
            if read_asset is not None:
                if match[1] not in images:
                    images[match[1]] = _image_bytes(match[1], read_asset)
                    asset_bytes += len(images[match[1]])
                    if asset_bytes > MAX_COMPOSITION_ASSET_BYTES:
                        raise DomainError('carousel_svg_limit', 'Unique image bytes exceed the composition budget')
        stack.extend((child, depth + 1, in_definition or tag in _DEFINITIONS, family, bold) for child in node)
    if any(ids.get(ident) not in expected for ident, expected in references):
        raise DomainError('carousel_svg_invalid', 'A referenced local definition is missing or has the wrong type')
    return ET.tostring(root, encoding='utf-8')


def render_svg(svg, *, card_count, card_width, card_height, read_asset) -> bytes:
    """Render one long canvas; no generation, network, provider or publication."""
    from cairosvg.surface import PNGSurface, cairo
    width, height = _dimensions(card_count, card_width, card_height)
    assets = {}

    def collect(ident):
        result = read_asset(ident)
        assets['asset:' + ident] = result[0]
        return result

    source = validate_svg(svg, card_count=card_count, card_width=card_width,
                          card_height=card_height, read_asset=collect)

    def private_fetch(url, _resource_type):
        if url not in assets:
            raise DomainError('carousel_svg_unsafe', 'Only prevalidated private assets are available')
        return assets[url]

    try:
        return PNGSurface.convert(bytestring=source, output_width=width, output_height=height,
                                  unsafe=False, background_color='#ffffff', url_fetcher=private_fetch)
    except (ValueError, TypeError, ArithmeticError, OSError, RecursionError,
            KeyError, IndexError, cairo.CairoError) as exc:
        raise DomainError('carousel_svg_invalid', 'The SVG cannot be rendered; check its geometry and attributes') from exc


def slice_cards(master_png, *, card_count, card_width, card_height) -> list[bytes]:
    """Crop exact adjacent windows; never rescale cards independently."""
    size = _dimensions(card_count, card_width, card_height)
    with Image.open(io.BytesIO(master_png)) as master:
        if master.format != 'PNG' or master.size != size:
            raise DomainError('carousel_dimensions_invalid', 'Master pixels do not match the card windows')
        master.load()
        cards = []
        for index in range(card_count):
            out = io.BytesIO()
            master.crop((index * card_width, 0, (index + 1) * card_width, card_height)).save(out, 'PNG')
            cards.append(out.getvalue())
        return cards
