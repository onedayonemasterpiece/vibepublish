"""Versioned SVG compositor: art and exact editorial copy remain separate layers.

Fixed trusted font files are read, never copied into output or repository files.
Glyph outlines make raster output independent of an SVG renderer's font fallback.
Pillow verifies/resizes inputs; layout/typography are vector recipe-owned.
"""
from __future__ import annotations
import base64
import hashlib
import html
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from PIL import Image
from .domain import DomainError, canonical, digest

PRESET = 'editorial-card-v1'
FORMATS = {'post_4_5': (1080, 1350), 'story_9_16': (1080, 1920)}
FONT_ROOT = Path('/usr/share/fonts/truetype/dejavu')


@lru_cache(maxsize=2)
def _font(bold: bool):
    path = FONT_ROOT / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
    if not path.is_file():
        raise DomainError('visual_font_not_available', next_action='contact_owner')
    raw = path.read_bytes()
    font = TTFont(io.BytesIO(raw))
    return font, hashlib.sha256(raw).hexdigest()


def _glyphs(text, bold):
    font, _ = _font(bold)
    cmap = font.getBestCmap()
    try:
        return [cmap[c] for c in map(ord, text)]
    except KeyError:
        raise DomainError('visual_glyph_needs_review', 'The preset does not cover a supplied character', 'fix_input') from None


def _width(text, size, bold):
    font, _ = _font(bold)
    return sum(font['hmtx'][glyph][0] for glyph in _glyphs(text, bold)) * size/font['head'].unitsPerEm


def _lines(text, width, size, bold):
    if any(ord(c) < 32 and c != '\n' for c in text) or any(c in '\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for c in text):
        raise DomainError('visual_copy_control_character')
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for word in paragraph.split():
            if _width(word, size, bold) > width:
                raise DomainError('visual_text_overflow', 'A word exceeds the fixed readable text width')
            candidate = line + (' ' if line else '') + word
            if _width(candidate, size, bold) > width:
                lines.append(line); line = word
            else:
                line = candidate
        lines.append(line)
    return lines


@dataclass(frozen=True, slots=True)
class Composite:
    png: bytes
    svg: bytes
    recipe_json: str
    width: int
    height: int


def render(art: bytes, copy: dict[str, str], format: str, preset=PRESET) -> Composite:
    if preset != PRESET or format not in FORMATS:
        raise DomainError('visual_preset_not_available')
    import cairosvg
    width, height = FORMATS[format]
    # No text is extracted or inferred from the art. Only explicit fields render.
    fields = [('title', 68, True), ('subtitle', 42, False), ('body', 34, False),
              ('date_line', 36, True), ('location_line', 32, False), ('source_line', 25, False)]
    if set(copy) - {f[0] for f in fields}:
        raise DomainError('visual_copy_field_invalid')
    with Image.open(io.BytesIO(art)) as image:
        image.verify()
    pad, bottom = 72, height-88
    art_height = (560 if format == 'post_4_5' else 960) if copy else height
    y = art_height + 90
    placed, paths, font_hashes = [], [], {}
    for field, size, bold in fields:
        text = copy.get(field)
        if not text:
            continue
        lines = _lines(text, width-2*pad, size, bold)
        font, sha = _font(bold)
        font_hashes['bold' if bold else 'regular'] = sha
        glyph_set = font.getGlyphSet()
        scale = size/font['head'].unitsPerEm
        for line in lines:
            if y+size*.25 > bottom:
                raise DomainError('visual_text_overflow', 'Text does not fit the fixed safe area; shorten the structured copy')
            x = float(pad)
            for glyph_name in _glyphs(line, bold):
                pen = SVGPathPen(glyph_set)
                glyph_set[glyph_name].draw(pen)
                path = pen.getCommands()
                if path:
                    paths.append(f'<path transform="translate({x:.4f},{y:.4f}) scale({scale:.8f},{-scale:.8f})" d="{path}"/>')
                x += font['hmtx'][glyph_name][0]*scale
            placed.append({'field': field, 'text': line, 'x': pad, 'baseline': y, 'width': x-pad,
                           'font_size': size, 'bold': bold})
            y += round(size*1.25)
        y += 18
    recipe = {'preset': PRESET, 'format': format, 'copy': copy, 'lines': placed,
              'font_sha256': font_hashes, 'safe_box': [pad, art_height+28, width-2*pad, bottom-art_height-28],
              'art_sha256': hashlib.sha256(art).hexdigest(), 'art_box': [0, 0, width, art_height],
              'renderer': 'svg-path-cairosvg-v1', 'human_review_required': True}
    encoded = base64.b64encode(art).decode('ascii')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
           f'<metadata>{html.escape(canonical(recipe))}</metadata>'
           f'<rect width="{width}" height="{height}" fill="#f8fafb"/>'
           f'<image x="0" y="0" width="{width}" height="{art_height}" preserveAspectRatio="xMidYMid slice" '
           f'xlink:href="data:image/png;base64,{encoded}"/>'
           f'<g fill="#172b3b">{"".join(paths)}</g></svg>').encode()
    # SVG is generated here, never user-supplied; its only URL is verified PNG data.
    png = cairosvg.svg2png(bytestring=svg, unsafe=False, output_width=width, output_height=height)
    return Composite(png, svg, canonical({**recipe, 'svg_sha256': hashlib.sha256(svg).hexdigest()}), width, height)
