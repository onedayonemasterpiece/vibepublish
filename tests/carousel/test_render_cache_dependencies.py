"""Warm and cold renders must respect current source-asset availability."""
import hashlib
import io

import pytest
from PIL import Image

from social_operations import carousel
from social_operations.assets import import_image
from social_operations.carousel import CarouselService
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store


@pytest.mark.parametrize("warm_cache", [False, True])
@pytest.mark.parametrize("kind", ["render", "export"])
def test_cached_canvas_respects_unavailable_source(tmp_path, warm_cache, kind):
    store = Store(tmp_path / "cache-dependencies.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)
    service = CarouselService(app)
    source = io.BytesIO()
    Image.new("RGB", (240, 256), "#173957").save(source, "PNG")
    asset = import_image(store, actor, source.getvalue(), "image/png")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="256">'
           f'<image href="asset:{asset}" width="720" height="256"/></svg>')
    story = service.command(actor, {"command": {
        "kind": "create", "brief": "Respect the actual source file",
        "card_count": 3, "card_width": 240, "card_height": 256, "svg": svg,
    }, "request_key": "create"})["carousel_id"]
    if warm_cache:
        service.command(actor, {"command": {
            "kind": "render", "carousel_id": story, "revision": 1, "card": 1,
        }})

    # Model loss of this dependency in the actual local Store, not a mocked read.
    with store.tx() as db:
        db.execute("DELETE FROM assets WHERE id=?", (asset,))
    with pytest.raises(DomainError) as direct:
        app.read_asset(actor, asset)
    assert direct.value.code == "asset_not_available"

    command = {"kind": kind, "carousel_id": story, "revision": 1}
    if kind == "render":
        command["card"] = 1
    with pytest.raises(DomainError) as failed:
        service.command(actor, {
            "command": command, "request_key": "after-source-became-unavailable",
        })
    assert failed.value.code == "asset_not_available"


def _saved_scene(store, actor, service, body, key):
    story = service.command(actor, {"command": {
        "kind": "create", "brief": "Cache dependencies", "card_count": 3,
        "card_width": 128, "card_height": 160,
        "svg": '<svg width="384" height="160">' + body + '</svg>',
    }, "request_key": key})["carousel_id"]
    with store.connection() as db:
        return service._version(db, actor, story, 1)


def test_cached_canvas_tracks_the_current_alpha_source(tmp_path):
    store = Store(tmp_path / "alpha-dependency.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)
    service = CarouselService(app)
    image = Image.new("RGBA", (80, 80), (255, 255, 255, 0))
    image.paste((240, 45, 25, 255), (20, 20, 60, 60))
    source = io.BytesIO()
    image.save(source, "PNG")
    asset = import_image(store, actor, source.getvalue(), "image/png")
    row = _saved_scene(store, actor, service,
        '<rect width="384" height="160" fill="#173957"/>'
        f'<image href="asset:{asset}" x="110" width="80" height="80"/>', "alpha")
    warm = service._render(actor, row)
    with store.tx() as db:
        original = db.execute('SELECT id FROM assets WHERE sha256=? AND id!=?',
            (hashlib.sha256(source.getvalue()).hexdigest(), asset)).fetchone()[0]
        db.execute('DELETE FROM assets WHERE id=?', (original,))

    # The existing resolver now selects the retained derivative. A warm canvas
    # must match that cold result, not keep pixels from the unavailable original.
    actual = service._render(actor, row)
    with carousel._RENDERED_LOCK:
        carousel._RENDERED.clear()
    cold = service._render(actor, row)
    assert actual == cold and actual != warm
    with Image.open(io.BytesIO(actual)) as rendered:
        assert rendered.convert('RGB').getpixel((111, 1)) == (255, 255, 255)


def test_expired_cached_original_does_not_shadow_durable_alpha_source(tmp_path):
    now = [1_800_000_000]
    store = Store(tmp_path / "original-expiry.sqlite", clock=lambda: now[0])
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)
    service = CarouselService(app)
    image = Image.new("RGBA", (80, 80), (255, 255, 255, 0))
    image.paste((240, 45, 25, 255), (20, 20, 60, 60))
    source = io.BytesIO()
    image.save(source, "PNG")
    raw = source.getvalue()
    source_sha = hashlib.sha256(raw).hexdigest()

    # Native reads can cache the raw PNG before a later ordinary import creates
    # its durable original and its distinct white-backed derivative.
    cached = "asset_early_cache"
    with store.tx() as db:
        db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)",
            (cached, actor.tenant_id, actor.principal_id, source_sha,
             "image/png", 80, 80, raw, source_sha, now[0]))
        db.execute("INSERT INTO media_store_assets VALUES(?,?,?,?)",
                   (cached, None, "download_cache", now[0] + 1))
    asset = import_image(store, actor, raw, "image/png")
    row = _saved_scene(store, actor, service,
        '<rect width="384" height="160" fill="#173957"/>'
        f'<image href="asset:{asset}" x="110" width="80" height="80"/>', "expiry")
    expected = service._render(actor, row)
    with store.connection() as db:
        originals = [r[0] for r in db.execute(
            "SELECT id FROM assets WHERE sha256=? ORDER BY rowid", (source_sha,))]
        assert originals[0] == cached and len(originals) == 2

    now[0] += 2  # Logical expiry, before the worker's physical cleanup.
    assert service._render(actor, row) == expected
    with Image.open(io.BytesIO(expected)) as rendered:
        assert rendered.convert("RGB").getpixel((111, 1)) == (23, 57, 87)


def test_render_cache_evicts_to_byte_budget_and_skips_oversized_png(tmp_path, monkeypatch):
    import resvg_py

    store = Store(tmp_path / "cache-budget.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    service = CarouselService(Application(store))
    rows = [_saved_scene(store, actor, service,
        f'<rect id="shape{i}" width="384" height="160" fill="#173957"/>', f"scene{i}")
        for i in range(3)]
    calls = []
    rasterize = resvg_py.svg_to_bytes

    def counted(**kwargs):
        calls.append(1)
        return rasterize(**kwargs)

    monkeypatch.setattr(resvg_py, 'svg_to_bytes', counted)
    with carousel._RENDERED_LOCK:
        carousel._RENDERED.clear()
    first = service._render(actor, rows[0])
    with Image.open(io.BytesIO(first)) as png:
        assert png.format == 'PNG' and png.size == (384, 160)
    budget = 2 * len(first)
    monkeypatch.setattr(carousel, '_RENDERED_MAX_BYTES', budget, raising=False)
    assert service._render(actor, rows[1]) == first
    assert service._render(actor, rows[0]) == first  # Move the first entry to MRU.
    assert service._render(actor, rows[2]) == first
    assert len(calls) == 3
    with carousel._RENDERED_LOCK:
        assert len(carousel._RENDERED) == 2
        assert sum(map(len, carousel._RENDERED.values())) <= budget
    service._render(actor, rows[0])
    assert len(calls) == 3
    service._render(actor, rows[1])
    assert len(calls) == 4  # The least-recently used entry was evicted.

    with carousel._RENDERED_LOCK:
        carousel._RENDERED.clear()
    monkeypatch.setattr(carousel, '_RENDERED_MAX_BYTES', len(first) - 1)
    assert service._render(actor, rows[0]) == first
    assert not carousel._RENDERED
