"""Private SVG carousel composition with bounded, local-only resources.

The model authors SVG geometry and explicit text lines. The application resolves
asset IDs with its existing ACL; this module never opens a model-supplied URL.
"""
from __future__ import annotations

import base64
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
_SVG = 'http://www.w3.org/2000/svg'
_XLINK = 'http://www.w3.org/1999/xlink'
_NUMBER = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?')
_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,127}')
_ASSET = re.compile(r'(?:asset:|vibepublish://assets/)([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})')
_LOCAL_URL = re.compile(r"url\s*\(\s*['\"]?#([A-Za-z_][A-Za-z0-9_.-]{0,127})['\"]?\s*\)", re.I)
_NUMERIC = set(('x y dx dy x1 y1 x2 y2 cx cy r rx ry fx fy width height d points '
                'transform gradientTransform font-size letter-spacing stroke-width '
                'stroke-miterlimit stroke-dasharray stroke-dashoffset rotate '
                'stdDeviation patternTransform filterRes').split())
_FONT_DIR = Path(__file__).resolve().parent / 'fonts'
# (regular, bold, italic, bold-italic); variable fonts share an exact font file.
_FONT_VARIANTS = {
    'Oswald': ('Oswald[wght].ttf',) * 4,
    'Unbounded': ('Unbounded[wght].ttf',) * 4,
    'Montserrat': ('Montserrat[wght].ttf',) * 2 + ('Montserrat-Italic[wght].ttf',) * 2,
    'PT Serif': ('PT_Serif-Web-Regular.ttf', 'PT_Serif-Web-Bold.ttf',
                 'PT_Serif-Web-Italic.ttf', 'PT_Serif-Web-BoldItalic.ttf'),
}
FONTS = tuple(_FONT_VARIANTS)
_RENDER_FONT_FILES = tuple(str(_FONT_DIR / name)
                           for name in sorted({name for variants in _FONT_VARIANTS.values() for name in variants}))


def _dimensions(card_count, card_width, card_height):
    if (any(type(v) is not int for v in (card_count, card_width, card_height))
            or not 3 <= card_count <= 10
            or not 128 <= card_width <= 2560 or not 128 <= card_height <= 2560
            or card_count * card_width * card_height > 20_000_000):
        raise DomainError('carousel_dimensions_invalid')
    return card_count * card_width, card_height


@lru_cache(maxsize=16)
def _font_chars(path: Path):
    if not path.is_file():
        raise DomainError('carousel_font_not_available', 'Packaged OFL font file is missing', 'contact_owner')
    with TTFont(path) as font:
        return frozenset(font.getBestCmap())


def _resolve_font(family: str, weight: int, italic: bool):
    if family not in _FONT_VARIANTS:
        raise DomainError('carousel_font_not_available', 'Fonts: Oswald, Unbounded, Montserrat, PT Serif')
    filename = _FONT_VARIANTS[family][int(weight >= 600) + 2 * italic]
    return _FONT_DIR / filename


def _font_selection(attrs, inherited):
    family, weight, italic = inherited
    style = attrs.get('style', '')
    css = {name.lower(): value.strip() for name, value in re.findall(
        r'(?:^|;)\s*(font-family|font-weight|font-style)\s*:\s*([^;]+)', style, re.I)}
    value = attrs.get('font-family', css.get('font-family'))
    if value:
        names = [part.strip().strip('"\'') for part in value.split(',')]
        family = next((name for name in names if name in FONTS), names[0])
    value = attrs.get('font-weight', css.get('font-weight', '')).strip().lower()
    if value:
        if value == 'normal':
            weight = 400
        elif value == 'bold':
            weight = 700
        elif value == 'bolder':
            weight = min(weight + 300, 900)
        elif value == 'lighter':
            weight = max(weight - 300, 100)
        elif value not in {'inherit', 'unset'}:
            if not value.isdecimal() or not 100 <= int(value) <= 900:
                raise DomainError('carousel_font_not_available', 'Use a bundled variable/static font weight')
            weight = int(value)
    value = attrs.get('font-style', css.get('font-style', '')).strip().lower()
    if value and value not in {'inherit', 'unset'}:
        italic = value.startswith(('italic', 'oblique'))
        if not italic and value != 'normal':
            raise DomainError('carousel_font_not_available', 'Use normal, italic or oblique')
    return family, weight, italic


def _safe_local_urls(value: str):
    if re.search(r'@import\b', value, re.I):
        raise DomainError('carousel_svg_unsafe', 'CSS imports are forbidden')
    without_local = _LOCAL_URL.sub('', value)
    if re.search(r'url\s*\(', without_local, re.I):
        raise DomainError('carousel_svg_unsafe', 'Only local url(#id) references are permitted')


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
    """Preserve ordinary SVG; reject code, external references and bounded-resource abuse."""
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
        raise DomainError('carousel_svg_invalid', 'SVG must be XML without DTDs or entities') from exc
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
    root.set('font-family', root.get('font-family', 'Montserrat'))
    seen_ids, links, images = set(), [], set()
    stack = [(root, 0, ('Montserrat', 400, False))]
    count = text_count = asset_bytes = 0
    while stack:
        node, depth, font = stack.pop()
        count += 1
        if count > 1200 or depth > 24:
            raise DomainError('carousel_svg_limit', 'SVG is too complex')
        tag = node.tag.rsplit('}', 1)[-1]
        if tag.lower() in {'script', 'foreignobject'}:
            raise DomainError('carousel_svg_unsafe', 'Script and foreignObject are forbidden')
        if not node.tag.startswith('{'):
            node.tag = '{' + _SVG + '}' + tag
        attrs = {}
        for raw_key, value in node.attrib.items():
            key = raw_key.rsplit('}', 1)[-1]
            if key.lower().startswith('on') or key == 'base' and raw_key.endswith('}base'):
                raise DomainError('carousel_svg_unsafe', 'SVG events and external bases are forbidden')
            if len(value) > 32_768:
                raise DomainError('carousel_svg_limit', 'SVG attribute is too large')
            _safe_local_urls(value)
            if key == 'style' and '\\' in value:
                raise DomainError('carousel_svg_unsafe', 'Escaped CSS resources are forbidden')
            if key == 'href':
                if raw_key not in {'href', '{' + _XLINK + '}href'}:
                    raise DomainError('carousel_svg_unsafe', 'Untrusted href namespace')
                match = _ASSET.fullmatch(value)
                if match:
                    if tag != 'image':
                        raise DomainError('carousel_svg_unsafe', 'Assets are allowed only in image elements')
                    value = 'asset:' + match[1]
                    if match[1] not in images:
                        images.add(match[1])
                        if read_asset is not None:
                            asset_bytes += len(_image_bytes(match[1], read_asset))
                            if asset_bytes > MAX_COMPOSITION_ASSET_BYTES:
                                raise DomainError('carousel_svg_limit', 'Unique image bytes exceed the composition budget')
                elif not (value.startswith('#') and _ID.fullmatch(value[1:])):
                    raise DomainError('carousel_svg_unsafe', 'href must be asset:ID or #id')
            if key in _NUMERIC and (re.search(r'\b(?:nan|inf(?:inity)?)\b', value, re.I)
                                    or any(not math.isfinite(float(n)) or abs(float(n)) > 100_000
                                           for n in _NUMBER.findall(value))):
                raise DomainError('carousel_svg_limit', 'SVG coordinates are out of bounds')
            if key == 'font-size' and re.fullmatch(r'\d+(?:\.\d+)?(?:px)?', value):
                if not 1 <= float(value.removesuffix('px')) <= 2560:
                    raise DomainError('carousel_svg_limit', 'Font size is out of bounds')
            if raw_key == '{' + _XLINK + '}href':
                raw_key = 'href'
            if raw_key in attrs:
                raise DomainError('carousel_svg_invalid', 'Duplicate href')
            attrs[raw_key] = value
            for ident in re.findall(r'url\s*\(\s*[\'"]?#([A-Za-z_][A-Za-z0-9_.-]{0,127})', value, re.I):
                links.append(ident)
        node.attrib.clear()
        node.attrib.update(attrs)
        if 'id' in attrs:
            if not _ID.fullmatch(attrs['id']) or attrs['id'] in seen_ids:
                raise DomainError('carousel_svg_invalid', 'SVG IDs must be unique')
            seen_ids.add(attrs['id'])
        text = (node.text or '') + ''.join(child.tail or '' for child in node)
        text_count += len(text)
        if text_count > 16_000:
            raise DomainError('carousel_svg_limit', 'SVG contains too much text')
        if tag == 'style' and ('\\' in text or re.search(r'@import\b|url\s*\(', text, re.I)):
            raise DomainError('carousel_svg_unsafe', 'Stylesheets cannot load resources')
        font = _font_selection(attrs, font)
        if tag in {'text', 'tspan'}:
            missing = [c for c in text if not c.isspace() and ord(c) not in _font_chars(_resolve_font(*font))]
            if missing:
                raise DomainError('carousel_glyph_not_available', 'The selected bundled font lacks text glyphs')
        stack.extend((child, depth + 1, font) for child in node)
    if any(ident not in seen_ids for ident in links):
        raise DomainError('carousel_svg_invalid', 'A local paint/filter/mask definition is missing')
    return ET.tostring(root, encoding='utf-8')


def _filter_layers(root, layers):
    """Keep SVG definitions and ancestors, selecting or hiding painted subtrees by id."""
    if not isinstance(layers, dict) or len(layers) != 1:
        raise DomainError('carousel_layers_invalid')
    mode, requested = next(iter(layers.items()))
    if mode not in {'only', 'hide'} or not isinstance(requested, list) or not requested or any(
            not isinstance(ident, str) for ident in requested):
        raise DomainError('carousel_layers_invalid')
    ids = set(requested)
    if ids - {node.get('id') for node in root.iter()}:
        raise DomainError('carousel_layer_not_found', 'Select existing SVG element ids')
    resources = {'defs', 'style', 'symbol', 'linearGradient', 'radialGradient',
                 'clipPath', 'mask', 'pattern', 'filter', 'marker'}

    def retain(node, selected=False):
        if mode == 'hide' and node.get('id') in ids:
            return False
        if mode == 'only' and node.tag.rsplit('}', 1)[-1] in resources:
            return True
        selected = selected or (mode == 'only' and node.get('id') in ids)
        for child in list(node):
            if not retain(child, selected):
                node.remove(child)
        return mode == 'hide' or selected or len(node) > 0

    for child in list(root):
        if not retain(child):
            root.remove(child)


def render_svg(svg, *, card_count, card_width, card_height, read_asset, layers=None) -> bytes:
    """Standard resvg shaping/kerning with no system fonts or external resources."""
    import resvg_py
    width, height = _dimensions(card_count, card_width, card_height)
    assets = {}

    def collect(ident):
        result = read_asset(ident)
        assets[ident] = (result[0], result[1])
        return result

    source = validate_svg(svg, card_count=card_count, card_width=card_width,
                          card_height=card_height, read_asset=collect)
    root = ET.fromstring(source)
    if layers is not None:
        _filter_layers(root, layers)
    definitions = ET.SubElement(root, '{' + _SVG + '}defs')
    reused = {}
    reserved_ids = {n.get('id') for n in root.iter() if n.get('id')}
    for node in list(root.iter()):
        if node.tag != '{' + _SVG + '}image':
            continue
        match = _ASSET.fullmatch(node.get('href', ''))
        if not match:
            continue
        ident = match[1]
        data, mime = assets[ident]
        alignment = node.get('preserveAspectRatio', 'xMidYMid meet')
        key = ident, alignment
        if key not in reused:
            with Image.open(io.BytesIO(data)) as im:
                natural_width, natural_height = im.size
            name = f'_vp_private_image_{len(reused)}'
            while name in reserved_ids:
                name += '_'
            reserved_ids.add(name)
            symbol = ET.SubElement(definitions, '{' + _SVG + '}symbol', {
                'id': name, 'viewBox': f'0 0 {natural_width} {natural_height}',
                'preserveAspectRatio': alignment})
            ET.SubElement(symbol, '{' + _SVG + '}image', {
                'width': str(natural_width), 'height': str(natural_height),
                'href': 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')})
            reused[key] = name
        attrs = dict(node.attrib)
        node.tag = '{' + _SVG + '}use'
        node.attrib.clear()
        node.attrib.update({k: v for k, v in attrs.items() if k not in {'href', 'preserveAspectRatio'}})
        node.set('href', '#' + reused[key])
    try:
        return resvg_py.svg_to_bytes(svg_string=ET.tostring(root, encoding='unicode'),
                                     width=width, height=height, background='#ffffff',
                                     skip_system_fonts=True, font_files=list(_RENDER_FONT_FILES),
                                     font_family='Montserrat', serif_family='PT Serif',
                                     sans_serif_family='Montserrat')
    except (ValueError, TypeError, OSError, RuntimeError, OverflowError) as exc:
        raise DomainError('carousel_svg_invalid', 'The SVG cannot be rendered') from exc


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
