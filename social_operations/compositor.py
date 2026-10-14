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
import math
import re
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


def render(art: bytes, copy: dict[str, str], format: str, preset=PRESET, *, source_layout=None) -> Composite:
    if preset != PRESET or format not in FORMATS and not (format == 'original' and source_layout is not None):
        raise DomainError('visual_preset_not_available')
    import cairosvg
    width, height = FORMATS.get(format, (1080, 1350))
    # No text is extracted or inferred from the art. Only explicit fields render.
    fields = [('title', 68, True), ('subtitle', 42, False), ('body', 34, False),
              ('date_line', 36, True), ('location_line', 32, False), ('source_line', 25, False)]
    if source_layout is not None:
        box = source_layout.get('text_box')
        if (not isinstance(box, list) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box)
                or box[2] <= 0 or box[3] <= 0 or box[0]+box[2] > 1 or box[1]+box[3] > 1):
            raise DomainError('source_frame_layout_invalid')
        fields = [('title', source_layout.get('title_size', 42), True), ('subtitle', 30, False),
                  ('body', source_layout.get('body_size', 28), False), ('date_line', 28, True),
                  ('location_line', 24, False), ('source_line', 22, False)]
        if any(type(size) not in (int, float) or not math.isfinite(size) or not 22 <= size <= 68 for _, size, _ in fields):
            raise DomainError('source_frame_layout_invalid')
        if (not re.fullmatch(r'#[a-fA-F0-9]{6}', source_layout.get('text_color', '#ffffff'))
                or type(source_layout.get('backplate_opacity', 0)) not in (int, float)
                or not 0 <= source_layout.get('backplate_opacity', 0) <= .65):
            raise DomainError('source_frame_layout_invalid')
    if set(copy) - {f[0] for f in fields}:
        raise DomainError('visual_copy_field_invalid')
    with Image.open(io.BytesIO(art)) as image:
        image.verify()
        source_width, source_height = image.size
    if source_layout is not None:
        if format == 'original':
            width, height = source_width, source_height
        elif format == 'post_4_5' and 5*source_width != 4*source_height:
            raise DomainError('source_frame_requires_true_crop', '4:5 requires already cropped source pixels, never contain padding')
        elif format == 'story_9_16' and 16*source_width != 9*source_height:
            raise DomainError('source_frame_requires_true_crop')
        # Caller font sizes are readable pixels at a 1080-wide presentation.
        # Original keeps all source pixels and aspect; typography scales with it.
        fields = [(field, size*width/1080, bold) for field, size, bold in fields]
    # Finished artwork already carries its lettering. Keep its aspect ratio
    # instead of adding a blank card around it; the format bounds its size.
    if not copy and source_layout is None:
        scale = min(width/source_width, height/source_height)
        width = max(1, round(source_width*scale))
        height = max(1, round(source_height*scale))
    pad, bottom = 72, height-88
    art_height = height if source_layout is not None else (560 if format == 'post_4_5' else 960) if copy else height
    art_scale = min(width/source_width, art_height/source_height)
    content_width, content_height = source_width*art_scale, source_height*art_scale
    content_box = [(width-content_width)/2, (art_height-content_height)/2, content_width, content_height]
    if not copy:
        content_box = [0, 0, width, height]
    y = art_height + 90
    text_width = width-2*pad
    safe_box = [pad, art_height+28, text_width, bottom-art_height-28]
    backplate = ''
    if source_layout is not None:
        left, top, text_width, text_height = [value*extent for value, extent in zip(box, (width, height, width, height))]
        pad, bottom = left, top+text_height
        safe_box = [left, top, text_width, text_height]
        y = top + next((size for field, size, _ in fields if copy.get(field)), 0)
        opacity = source_layout.get('backplate_opacity', 0)
        backplate = f'<rect x="{left}" y="{top}" width="{text_width}" height="{text_height}" fill="#0b2943" fill-opacity="{opacity}"/>'
    placed, paths, font_hashes = [], [], {}
    for field, size, bold in fields:
        text = copy.get(field)
        if not text:
            continue
        lines = _lines(text, text_width, size, bold)
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
            y += size*1.25 if source_layout is not None else round(size*1.25)
        y += 8 if source_layout is not None else 18
    recipe = {'preset': PRESET, 'format': format, 'copy': copy, 'lines': placed,
              'font_sha256': font_hashes, 'safe_box': safe_box,
              'art_sha256': hashlib.sha256(art).hexdigest(), 'art_box': [0, 0, width, art_height],
              'art_fit': 'contain', 'art_source_size': [source_width, source_height],
              'art_content_box': content_box,
              'canvas_fit': 'fixed' if copy else 'art_aspect',
              'renderer': 'svg-path-cairosvg-v5-photo-choice' if source_layout is not None else 'svg-path-cairosvg-v3',
              'human_review_required': True}
    if source_layout is not None:
        recipe['source_layout'] = source_layout
    image_layer = art
    if not copy:
        # Resize once to integer pixel dimensions before SVG composition so
        # Cairo cannot blend a fractional image edge into the card background.
        with Image.open(io.BytesIO(art)) as source:
            resized = source.resize((width, height), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            resized.save(output, format='PNG')
            image_layer = output.getvalue()
    encoded = base64.b64encode(image_layer).decode('ascii')
    # The native-aspect dimensions are rounded to whole pixels. Filling that
    # box avoids fractional-pixel antialiased borders from SVG's meet fitting.
    aspect_fit = 'xMidYMid meet' if copy else 'none'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
           f'<metadata>{html.escape(canonical(recipe))}</metadata>'
           f'<rect width="{width}" height="{height}" fill="#f8fafb"/>'
           f'<image x="0" y="0" width="{width}" height="{art_height}" preserveAspectRatio="{aspect_fit}" '
           f'xlink:href="data:image/png;base64,{encoded}"/>'
           + backplate
           + f'<g fill="{source_layout.get("text_color", "#ffffff") if source_layout is not None else "#172b3b"}">{"".join(paths)}</g></svg>').encode()
    # SVG is generated here, never user-supplied; its only URL is verified PNG data.
    png = cairosvg.svg2png(bytestring=svg, unsafe=False, output_width=width, output_height=height)
    return Composite(png, svg, canonical({**recipe, 'svg_sha256': hashlib.sha256(svg).hexdigest()}), width, height)
