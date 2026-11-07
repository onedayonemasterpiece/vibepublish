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
from urllib.parse import quote, urlencode
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
_ICONIFY = "https://api.iconify.design"
_ICONIFY_PAGE = "https://icon-sets.iconify.design"
_ID = re.compile(r"(?:[1-9][0-9]{0,9}|[a-z0-9-]{1,40}:[a-z0-9-]{1,80})\Z")
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
# Iconify uses ph:dove-fill and mdi:dove-outline as icon names, not set prefixes.
_ICONIFY_PREFIXES = {
    "outlined": ("lucide", "tabler", "ph", "mdi", "mdi-light"),
    "filled": ("mdi", "fa6-solid", "ph"),
    "illustrative": ("openmoji", "fluent-emoji-flat", "noto"),
}


def _style_matches(ident: str, category: str) -> bool:
    prefix, name = ident.split(":", 1)
    if category == "outlined":
        return (prefix in {"lucide", "mdi-light"}
                or prefix == "tabler" and not name.endswith("-filled")
                or prefix == "ph" and not name.endswith(("-fill", "-bold", "-duotone"))
                or prefix == "mdi" and name.endswith("-outline"))
    if category == "filled":
        return (prefix == "fa6-solid"
                or prefix == "mdi" and not name.endswith("-outline")
                or prefix == "ph" and name.endswith("-fill"))
    return True


def _fetch(url: str, limit: int) -> bytes:
    """Bound each SVG Repo response; URL is assembled exclusively by this module."""
    if not url.startswith((_SITE + "/", _ICONIFY + "/")):
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
                    or not (metadata["source"].startswith(_SITE + "/svg/")
                            or (":" in ident and metadata["source"] ==
                                _ICONIFY_PAGE + "/" + ident.replace(":", "/") + "/"))
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

    def _cache(self, row, svg):
        _save(self.root / (row["id"] + ".svg"), svg.encode("utf-8"))
        _save(self.root / (row["id"] + ".json"),
              json.dumps(row, ensure_ascii=False).encode("utf-8"))

    def _iconify_search(self, query, style, found, seen):
        """Search Iconify by meaning/style; read the actual icon-set license."""
        category = _STYLE_ALIASES.get(style.casefold(), style.casefold())
        parameters = {"query": query, "limit": 64}
        if category in _ICONIFY_PREFIXES:
            parameters["prefixes"] = ",".join(_ICONIFY_PREFIXES[category])
        search = json.loads(_fetch(_ICONIFY + "/search?" + urlencode(parameters), 1024 * 1024))
        if not isinstance(search, dict) or not isinstance(search.get("icons"), list):
            raise ValueError("Invalid Iconify search response")
        candidates = [ident for ident in search["icons"]
                      if isinstance(ident, str) and _ID.fullmatch(ident)
                      and ":" in ident and ident not in seen
                      and _style_matches(ident, category)]
        if not candidates:
            return
        prefixes = sorted({ident.split(":", 1)[0] for ident in candidates[:32]})
        collections = search.get("collections", {})
        collections = dict(collections) if isinstance(collections, dict) else {}
        try:
            details = json.loads(_fetch(_ICONIFY + "/collections?" +
                        urlencode({"prefixes": ",".join(prefixes)}), 512 * 1024))
            if isinstance(details, dict):
                collections.update(details)
        except (URLError, OSError, ValueError, TimeoutError):
            pass  # Search results already include the collection metadata.
        for ident in candidates[:32]:
            if len(found) >= 8:
                break
            prefix, name = ident.split(":", 1)
            try:
                svg = _clean_svg(_fetch(f"{_ICONIFY}/{prefix}/{name}.svg", 256 * 1024))
                _thumb(svg)
            except (URLError, OSError, ValueError, DomainError, TimeoutError):
                continue
            collection = collections.get(prefix, {})
            collection = collection if isinstance(collection, dict) else {}
            license_info = collection.get("license", {})
            license_info = license_info if isinstance(license_info, dict) else {}
            license_name = license_info.get("spdx") or license_info.get("title")
            if not isinstance(license_name, str) or not license_name.strip():
                license_name = "Unverified — check source"
            row = {"id": ident, "name": name.replace("-", " ").title(),
                   "source": f"{_ICONIFY_PAGE}/{prefix}/{name}/",
                   "license": license_name[:100], "style": style}
            self._cache(row, svg)
            found.append((row, svg))
            seen.add(ident)

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
                    self._cache(row, svg)
                    found.append((row, svg))
                    if len(found) == 8:
                        break
            except (URLError, OSError, ValueError, TimeoutError):
                pass  # SVG Repo may return HTTP 429 for every page.
        if not found:
            try:
                self._iconify_search(query.strip(), style, found, seen)
            except (URLError, OSError, ValueError, TimeoutError) as exc:
                raise DomainError("carousel_icon_search_unavailable",
                                  "SVG Repo and Iconify search are unavailable") from exc
        self._authorize(actor)
        if not found:
            return {"private": True, "icons": []}
        canvas = Image.new("RGB", (800, 480), "white")
        pen = ImageDraw.Draw(canvas)
        font = ImageFont.load_default(size=15)
        tiny = ImageFont.load_default(size=11)
        for n, (row, svg) in enumerate(found):
            x, y = (n % 4) * 200, (n // 4) * 240
            pen.rectangle((x + 4, y + 4, x + 196, y + 234), outline="#dddddd")
            symbol = _thumb(svg)
            canvas.paste(symbol, (x + 10, y + 12), symbol)
            small = symbol.resize((28, 28), Image.Resampling.LANCZOS)
            canvas.paste(small, (x + 163, y + 130), small)
            pen.text((x + 12, y + 171), row["id"][:29], font=tiny, fill="#111111")
            pen.text((x + 12, y + 193), row["name"][:23], font=font, fill="#444444")
            provider = "Iconify" if ":" in row["id"] else "SVG Repo"
            pen.text((x + 12, y + 215), (provider + " · " + row["license"])[:28],
                     font=tiny, fill="#666666")
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
            raise DomainError("carousel_icon_not_found", "Search icons to cache an icon first")
        row, svg = cached
        self._authorize(actor)
        return {"private": True, "icon": row, "svg": svg}
