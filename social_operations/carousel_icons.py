"""Local-first SVG Repo icon lookup for the existing private carousel MCP tool.

Cache individual cleaned SVGs beside the ledger; no second icon catalog or service.
The SVG Repo URLs are constructed here, never accepted from model input.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
from html import unescape
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

import resvg_py
from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException
from PIL import Image, ImageDraw, ImageFont

from .assets import AssetPreview, render_asset_full
from .carousel_references import ReferenceBank
from .domain import DomainError

_SVG = "http://www.w3.org/2000/svg"
_XLINK = "http://www.w3.org/1999/xlink"
_SITE = "https://www.svgrepo.com"
_ID = re.compile(r"[1-9][0-9]{0,9}\Z")
_LINK = re.compile(
    r"""href\s*=\s*["'](?:https://www\.svgrepo\.com)?/svg/([1-9][0-9]{0,9})/([a-z0-9-]{1,100})["']""",
    re.I,
)
_LOCAL_PAINT = re.compile(r"url\(\s*['\"]?#[A-Za-z_][A-Za-z0-9_.-]{0,127}['\"]?\s*\)\Z", re.I)
_TAGS = frozenset((
    "svg g path rect circle ellipse line polyline polygon defs use symbol "
    "clipPath mask linearGradient radialGradient stop pattern title desc text tspan"
).split())
_ATTRS = frozenset((
    "id viewBox width height x y x1 x2 y1 y2 cx cy r rx ry d points "
    "transform fill fill-rule fill-opacity stroke stroke-width stroke-opacity "
    "stroke-linecap stroke-linejoin stroke-dasharray stroke-dashoffset "
    "stroke-miterlimit opacity color display visibility clip-path mask "
    "gradientUnits gradientTransform xlink:href offset stop-color stop-opacity "
    "patternUnits patternContentUnits patternTransform preserveAspectRatio "
    "font-family font-size font-weight text-anchor dx dy"
).split())
_STYLES = frozenset((
    "fill fill-rule fill-opacity stroke stroke-width stroke-opacity "
    "stroke-linecap stroke-linejoin stroke-dasharray stroke-dashoffset "
    "stroke-miterlimit opacity color display visibility clip-path mask"
).split())
_CATEGORIES = frozenset((
    "monocolor multicolor duotone outlined filled icon glyph rounded sharp"
).split())
_STYLE_ALIASES = {
    "line": "outlined", "outline": "outlined", "thin": "outlined",
    "тонкие": "outlined", "тонкая": "outlined", "контур": "outlined",
    "bold": "filled", "thick": "filled", "жирные": "filled", "заливка": "filled",
}


def _fetch(url: str, limit: int) -> bytes:
    """Bound each SVG Repo response; URL is assembled exclusively by this module."""
    if not url.startswith(_SITE + "/"):
        raise ValueError("Unexpected icon host")
    request = Request(url, headers={"User-Agent": "VibePublishCarousel/1.0"})
    with urlopen(request, timeout=10) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("SVG Repo response is too large")
    return data


def _license(page: bytes) -> str:
    plain = unescape(re.sub(r"<[^>]+>", " ", page.decode("utf-8", "replace")))
    plain = re.sub(r"\s+", " ", plain)
    after = re.search(r"\bLICENSE\s*:\s*(.{0,90})", plain, re.I)
    if after:
        for name in ("CC0 License", "SVG Repo License", "Public Domain",
                     "MIT License", "Apache License", "CC BY-SA", "CC BY-NC",
                     "CC BY", "GPL", "Logo License"):
            if name.casefold() in after.group(1).casefold():
                return name
    return "Unverified — check source"


def _clean_svg(raw: bytes) -> str:
    """Retain drawing primitives and local references, never active/external SVG content."""
    if not 0 < len(raw) <= 256 * 1024:
        raise DomainError("carousel_icon_unsafe", "Icon SVG exceeds the input bound")
    try:
        root = fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ET.ParseError, DefusedXmlException, UnicodeError, ValueError) as exc:
        raise DomainError("carousel_icon_unsafe", "Invalid or active SVG XML") from exc
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise DomainError("carousel_icon_unsafe", "SVG root required")

    count = 0

    def clean(node, depth=0):
        nonlocal count
        count += 1
        if count > 1200 or depth > 24:
            raise DomainError("carousel_icon_unsafe", "Icon SVG too complex")
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in _TAGS:
            return False
        attrs = {}
        for raw_name, value in node.attrib.items():
            name = raw_name.rsplit("}", 1)[-1]
            if name == "href":
                if tag == "use" and re.fullmatch(r"#[A-Za-z_][A-Za-z0-9_.-]{0,127}", value):
                    attrs["href"] = value
                continue
            if name == "style":
                for declaration in value.split(";"):
                    if ":" not in declaration:
                        continue
                    key, val = (v.strip() for v in declaration.split(":", 1))
                    if key in _STYLES and _safe_value(val):
                        attrs[key] = val
                continue
            if name in _ATTRS and _safe_value(value):
                attrs[name] = value
        node.attrib.clear()
        node.attrib.update(attrs)
        node.tag = "{" + _SVG + "}" + tag
        for child in list(node):
            if not clean(child, depth + 1):
                node.remove(child)
        return True

    clean(root)
    if not any(child.tag.rsplit("}", 1)[-1] not in {"title", "desc"} for child in root.iter() if child is not root):
        raise DomainError("carousel_icon_unsafe", "Icon contains no drawing")
    return ET.tostring(root, encoding="unicode")


def _safe_value(value: str) -> bool:
    if len(value) > 4096 or re.search(r"@import|expression\s*\(|javascript:|data:|\\", value, re.I):
        return False
    if "url(" in value.lower() and not _LOCAL_PAINT.fullmatch(value.strip()):
        return False
    if re.search(r"(?i)https?://|//|(?:^|[\s\"'])file:", value):
        return False
    return True


def _thumb(svg: str) -> Image.Image:
    try:
        png = resvg_py.svg_to_bytes(svg_string=svg, width=150, height=150,
                                    skip_system_fonts=True)
        with Image.open(io.BytesIO(png)) as source:
            return source.convert("RGBA")
    except (OSError, ValueError, TypeError, RuntimeError, OverflowError) as exc:
        raise DomainError("carousel_icon_unsafe", "SVG Repo icon cannot be rendered") from exc


def _save(path: Path, data: bytes):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(data)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp, path)


class IconBank:
    def __init__(self, store):
        self.store = store
        self.root = store.path.parent / "carousel-icons"

    def _authorize(self, actor):
        return ReferenceBank(self.store)._authorize(actor)

    def _saved(self, ident):
        if not _ID.fullmatch(ident):
            return None
        info = self.root / (ident + ".json")
        image = self.root / (ident + ".svg")
        if not info.is_file() or info.is_symlink() or not image.is_file() or image.is_symlink():
            return None
        try:
            metadata = json.loads(info.read_text(encoding="utf-8"))
            if (metadata.get("id") != ident or not isinstance(metadata.get("name"), str)
                    or not isinstance(metadata.get("source"), str)
                    or not metadata["source"].startswith(_SITE + "/svg/" )
                    or not isinstance(metadata.get("license"), str)
                    or image.stat().st_size > 256 * 1024):
                return None
            svg = _clean_svg(image.read_bytes())
            return metadata, svg
        except (OSError, UnicodeError, ValueError, DomainError):
            return None

    def _cached(self, query, style):
        if not self.root.is_dir():
            return []
        terms = query.casefold().split()
        matches = []
        for path in sorted(self.root.glob("*.json")):
            cached = self._saved(path.stem)
            if not cached:
                continue
            row, svg = cached
            if not all(term in row["name"].casefold() for term in terms):
                continue
            if style and row.get("style", "").casefold() != style.casefold():
                continue
            matches.append((row, svg))
            if len(matches) == 8:
                break
        return matches

    def search(self, actor, query: str, style: str = ""):
        self._authorize(actor)
        if (not isinstance(query, str) or not 1 <= len(query.strip()) <= 100
                or not isinstance(style, str) or len(style) > 60):
            raise DomainError("carousel_icon_query_invalid")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        found = self._cached(query.strip(), style)
        seen = {row["id"] for row, _ in found}
        if len(found) < 8:
            category = _STYLE_ALIASES.get(style.casefold(), style.casefold()) if style else ""
            terms = query if not style or category in _CATEGORIES else query + " " + style
            slug = quote(re.sub(r"\s+", "-", terms.strip().casefold()), safe="-")
            url = f"{_SITE}/vectors/{slug}/" + (category + "/" if category in _CATEGORIES else "")
            try:
                page = _fetch(url, 1024 * 1024).decode("utf-8", "replace")
                for ident, name in _LINK.findall(page):
                    if ident in seen:
                        continue
                    seen.add(ident)
                    source = f"{_SITE}/svg/{ident}/{name}"
                    try:
                        license_name = _license(_fetch(source, 1024 * 1024))
                        svg = _clean_svg(_fetch(f"{_SITE}/download/{ident}/{name}.svg", 256 * 1024))
                        _thumb(svg)
                    except (URLError, OSError, ValueError, DomainError, TimeoutError):
                        continue
                    row = {"id": ident, "name": name.replace("-", " ").title(),
                           "source": source, "license": license_name, "style": style}
                    _save(self.root / (ident + ".svg"), svg.encode("utf-8"))
                    _save(self.root / (ident + ".json"), json.dumps(
                        row, ensure_ascii=False).encode("utf-8"))
                    found.append((row, svg))
                    if len(found) == 8:
                        break
            except (URLError, OSError, ValueError, TimeoutError) as exc:
                if not found:
                    raise DomainError("carousel_icon_search_unavailable",
                                      "SVG Repo is unavailable and there are no cached matches") from exc
        self._authorize(actor)
        if not found:
            return {"private": True, "icons": []}
        canvas = Image.new("RGB", (800, 480), "white")
        pen = ImageDraw.Draw(canvas)
        font = ImageFont.load_default(size=15)
        for n, (row, svg) in enumerate(found):
            x, y = (n % 4) * 200, (n // 4) * 240
            pen.rectangle((x + 4, y + 4, x + 196, y + 234), outline="#dddddd")
            symbol = _thumb(svg)
            canvas.paste(symbol, (x + 10, y + 12), symbol)
            small = symbol.resize((28, 28), Image.Resampling.LANCZOS)
            canvas.paste(small, (x + 163, y + 130), small)
            pen.text((x + 12, y + 172), row["id"], font=font, fill="#111111")
            pen.text((x + 12, y + 194), row["name"][:23], font=font, fill="#444444")
        output = io.BytesIO()
        canvas.save(output, "PNG")
        image = output.getvalue()
        preview = render_asset_full(image, "image/png", hashlib.sha256(image).hexdigest(),
                                    "vibepublish://carousel-icons/grid")
        metadata = {**preview.metadata, "private": True, "icons": [row for row, _ in found]}
        return AssetPreview(metadata, preview.data)

    def get(self, actor, ident: str):
        self._authorize(actor)
        cached = self._saved(ident)
        if cached is None:
            raise DomainError("carousel_icon_not_found", "Search icons to cache a SVG Repo icon first")
        row, svg = cached
        self._authorize(actor)
        return {"private": True, "icon": row, "svg": svg}
