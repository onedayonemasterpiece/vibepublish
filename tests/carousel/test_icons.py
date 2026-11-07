"""Real MCP pixels, local-first cache and harmless inline SVG from mocked SVG Repo."""
import base64
import io
import json
from unittest.mock import patch
from urllib.error import URLError

from PIL import Image
from starlette.testclient import TestClient

from social_operations.carousel_icons import IconBank, _clean_svg
from social_operations.domain import DomainError
from social_operations.server import create_app
from social_operations.storage import Store


def test_icon_grid_and_safe_cached_svg_via_mcp(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    raw_svg = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" '
               b'onload="bad()"><script>alert(1)</script><foreignObject>x</foreignObject>'
               b'<path fill="#e12b38" onmouseover="bad()" d="M0 0H32V32H0Z"/>'
               b'<image href="https://evil.example/icon.png" width="32" height="32"/>'
               b'<use href="https://evil.example/icon.svg#x"/></svg>')
    urls = []

    def fake_fetch(url, limit):
        urls.append(url)
        if "/vectors/" in url:
            return b'<a href="/svg/342687/library-building">Library building</a>'
        if "/download/" in url:
            return raw_svg
        if "/svg/342687/" in url:
            return b'<p>LICENSE: <a>CC0 License</a></p><p>UPLOADER: SVG Repo</p>'
        raise AssertionError(url)

    with patch("social_operations.carousel_icons._fetch", side_effect=fake_fetch):
        with TestClient(create_app(store)) as client:
            client.headers.update({"Authorization": "Bearer " + token,
                                   "Accept": "application/json, text/event-stream"})

            def rpc(command, key=None):
                args = {"command": command}
                if key:
                    args["request_key"] = key
                response = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 2,
                    "method": "tools/call", "params": {"name": "vibepublish_carousel",
                    "arguments": args}})
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                assert not result.get("isError"), result
                return result

            initial = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1,
                "method": "initialize", "params": {"protocolVersion": "2025-11-25",
                "capabilities": {}, "clientInfo": {"name": "icon-test", "version": "1"}}})
            assert initial.status_code == 200
            created = rpc({"kind": "create", "brief": "Иконки"}, "icons-journal-create")
            carousel_id = created["structuredContent"]["carousel_id"]
            grid = rpc({"kind": "get", "scope": "icons", "carousel_id": carousel_id,
                        "query": "library", "style": "outlined"})
            assert len(grid["structuredContent"]["icons"]) == 1
            events = rpc({"kind": "get", "scope": "journal", "carousel_id": carousel_id})
            journal = events["structuredContent"]["journal"]
            icon_reads = [entry for entry in journal
                          if entry["kind"] == "get" and entry["scope"] == "icons"]
            assert len(icon_reads) == 1
            assert icon_reads[0]["duration_ms"] >= 0
            assert "library" not in json.dumps(icon_reads)
            icon = grid["structuredContent"]["icons"][0]
            assert icon["id"] == "342687"
            assert icon["license"] == "CC0 License"
            pictures = [b for b in grid["content"] if b["type"] == "image"]
            assert len(pictures) == 1 and pictures[0]["mimeType"] == "image/png"
            with Image.open(io.BytesIO(base64.b64decode(pictures[0]["data"]))) as picture:
                assert picture.size == (800, 480)
                assert picture.convert("RGB").getpixel((30, 30)) == (225, 43, 56)
            selection = rpc({"kind": "get", "scope": "icon", "id": icon["id"]})
            safe = selection["structuredContent"]["svg"]
            assert "script" not in safe and "foreignObject" not in safe
            assert "evil.example" not in safe and "onmouseover" not in safe
            assert '<' in safe and "path" in safe
            assert len(urls) == 3

    # A disconnected SVG Repo never prevents a previously selected cached icon.
    bank = IconBank(store)
    actor = store.authenticate(token)
    with patch("social_operations.carousel_icons._fetch", side_effect=URLError("offline")):
        offline = bank.search(actor, "library", "outlined")
    assert offline.metadata["icons"][0]["id"] == "342687"
    assert bank.get(actor, "342687")["svg"] == safe


def test_svg_cleaner_rejects_entities_and_disallows_external_paint():
    from pytest import raises
    with raises(DomainError):
        _clean_svg(b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>')
    clean = _clean_svg(b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<path fill="url(https://evil.example/a.svg)" style="stroke:#123456;'
        b'fill:url(javascript:bad)" d="M0 0L10 0"/></svg>')
    assert "evil.example" not in clean and "javascript:" not in clean
    assert "#123456" in clean


def test_svg_repo_429_falls_back_to_style_filtered_iconify_mcp_and_disk_cache(tmp_path):
    """A source that sends HTTP 429 on every endpoint must not break icon search."""
    from urllib.error import HTTPError

    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    urls = []
    dirty = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" '
             b'onload="evil()"><script>evil()</script><foreignObject/>'
             b'<path d="M0 0H32V32H0Z" fill="#e12b38" onmouseover="evil()"/>'
             b'<use href="https://evil.example/x.svg"/></svg>')

    def fake_fetch(url, limit):
        urls.append(url)
        if url.startswith("https://www.svgrepo.com/"):
            raise HTTPError(url, 429, "Too Many Requests", None, None)
        if "/search?" in url:
            assert "query=dove" in url and "prefixes=lucide" in url
            return json.dumps({"icons": ["lucide:dove", "ph:dove-fill", "tabler:dove"],
                "collections": {"lucide": {"license": {"spdx": "ISC"}}}}).encode()
        if "/collections?" in url:
            return json.dumps({"lucide": {"license": {"spdx": "ISC"}},
                               "tabler": {"license": {"title": "MIT License"}}}).encode()
        if url.endswith("/lucide/dove.svg") or url.endswith("/tabler/dove.svg"):
            return dirty
        raise AssertionError(url)

    with patch("social_operations.carousel_icons._fetch", side_effect=fake_fetch):
        with TestClient(create_app(store)) as client:
            client.headers.update({"Authorization": "Bearer " + token,
                                   "Accept": "application/json, text/event-stream"})

            def rpc(command):
                response = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 2,
                    "method": "tools/call", "params": {"name": "vibepublish_carousel",
                    "arguments": {"command": command}}})
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                assert not result.get("isError"), result
                return result

            initial = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1,
                "method": "initialize", "params": {"protocolVersion": "2025-11-25",
                "capabilities": {}, "clientInfo": {"name": "iconify-429", "version": "1"}}})
            assert initial.status_code == 200
            grid = rpc({"kind": "get", "scope": "icons", "query": "dove", "style": "line"})
            icons = grid["structuredContent"]["icons"]
            assert [icon["id"] for icon in icons] == ["lucide:dove", "tabler:dove"]
            assert [icon["license"] for icon in icons] == ["ISC", "MIT License"]
            assert icons[0]["source"] == "https://icon-sets.iconify.design/lucide/dove/"
            pictures = [block for block in grid["content"] if block["type"] == "image"]
            assert len(pictures) == 1 and pictures[0]["mimeType"] == "image/png"
            with Image.open(io.BytesIO(base64.b64decode(pictures[0]["data"]))) as picture:
                assert picture.size == (800, 480)
                assert picture.convert("RGB").getpixel((30, 30)) == (225, 43, 56)
            selection = rpc({"kind": "get", "scope": "icon", "id": "lucide:dove"})
            safe = selection["structuredContent"]["svg"]
            assert "script" not in safe and "foreignObject" not in safe
            assert "evil.example" not in safe and "onmouseover" not in safe
            assert "path" in safe
    assert any("/collections?" in url for url in urls)

    # Network remains blocked; the same icon can be selected from the disk cache.
    bank = IconBank(store)
    actor = store.authenticate(token)
    with patch("social_operations.carousel_icons._fetch",
               side_effect=HTTPError("https://www.svgrepo.com", 429, "Too Many Requests", None, None)):
        cached = bank.search(actor, "dove", "line")
    assert [row["id"] for row in cached.metadata["icons"]] == ["lucide:dove", "tabler:dove"]
    assert bank.get(actor, "lucide:dove")["svg"] == safe


def test_iconify_filled_filters_stroke_variants(tmp_path):
    from urllib.error import HTTPError

    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    icon = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0H24V24H0Z"/></svg>'

    def fake_fetch(url, limit):
        if url.startswith("https://www.svgrepo.com/"):
            raise HTTPError(url, 429, "blocked", None, None)
        if "/search?" in url:
            assert "prefixes=mdi" in url
            return json.dumps({"icons": ["lucide:dove", "mdi:dove-outline", "mdi:dove",
                                          "ph:dove", "ph:dove-fill", "fa6-solid:dove"],
                               "collections": {}}).encode()
        if "/collections?" in url:
            return json.dumps({p: {"license": {"spdx": "MIT"}}
                               for p in ("mdi", "ph", "fa6-solid")}).encode()
        if url.endswith(".svg"):
            return icon
        raise AssertionError(url)

    with patch("social_operations.carousel_icons._fetch", side_effect=fake_fetch):
        grid = IconBank(store).search(actor, "dove", "filled")
    assert [row["id"] for row in grid.metadata["icons"]] == [
        "mdi:dove", "ph:dove-fill", "fa6-solid:dove"
    ]


def test_iconify_outlined_excludes_tabler_filled_from_real_search_shape(tmp_path):
    from urllib.error import HTTPError

    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    # Actual /search?query=heart&prefixes=lucide,tabler,ph,mdi,mdi-light order.
    candidates = ["mdi:heart", "mdi:heart-outline", "mdi-light:heart", "tabler:heart",
                  "tabler:heart-filled", "lucide:heart", "ph:heart", "ph:heart-bold",
                  "ph:heart-duotone", "ph:heart-fill", "ph:heart-light", "ph:heart-thin"]
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0H24V24H0Z"/></svg>'

    def fake_fetch(url, limit):
        if url.startswith("https://www.svgrepo.com/"):
            raise HTTPError(url, 429, "Too Many Requests", None, None)
        if "/search?" in url:
            return json.dumps({"icons": candidates, "collections": {}}).encode()
        if "/collections?" in url:
            return b'{}'
        if url.endswith(".svg"):
            return svg
        raise AssertionError(url)

    with patch("social_operations.carousel_icons._fetch", side_effect=fake_fetch):
        grid = IconBank(store).search(actor, "heart", "line")
    assert [row["id"] for row in grid.metadata["icons"]] == [
        "mdi:heart-outline", "mdi-light:heart", "tabler:heart", "lucide:heart",
        "ph:heart", "ph:heart-light", "ph:heart-thin",
    ]
