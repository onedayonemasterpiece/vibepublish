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
