"""Export diagnostics expose the real cold/warm path without changing its result."""
import io
import logging
import sqlite3
import time

import pytest
from PIL import Image

import social_operations.carousel as carousel
from social_operations.assets import insert_verified_image, verify_image
from social_operations.service import Application
from social_operations.storage import Store


@pytest.fixture
def scene(tmp_path):
    store = Store(tmp_path / "private-export.sqlite")
    actor = store.authenticate(store.create_principal("private-tenant", "private-owner", owner=True))
    app = Application(store)
    service = carousel.CarouselService(app)
    output = io.BytesIO()
    Image.new("RGB", (4, 4), "#ee7700").save(output, "PNG")
    with store.tx() as db:
        ref = insert_verified_image(store, db, actor, verify_image(output.getvalue(), "image/png"))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
           '<rect width="384" height="160" fill="#173957"/>'
           f'<image href="asset:{ref}" x="10" y="10" width="16" height="16"/>'
           f'<image href="asset:{ref}" x="138" y="10" width="16" height="16"/>'
           '</svg>')
    created = service.command(actor, {"command": {"kind": "create", "brief": "Private export",
        "card_count": 3, "card_width": 128, "card_height": 160, "svg": svg},
        "request_key": "private-create"})
    command = {"kind": "export", "carousel_id": created["carousel_id"], "revision": 1}
    return store, actor, app, service, command, ref


def receipt_without_cursor(receipt):
    # Each receipt read creates a fresh progress cursor; the completion is unchanged.
    return {**receipt, "progress": {key: value for key, value in receipt["progress"].items()
                                  if key != "cursor"}}


def inventory(store):
    with store.connection() as db:
        return tuple(db.execute("SELECT count(*),sum(length(bytes)) FROM assets").fetchone()), (
            db.execute("SELECT count(*) FROM operations").fetchone()[0])


def test_export_phases_observer_is_after_release_and_cannot_change_cold_warm_or_replay(scene, monkeypatch):
    store, actor, app, service, command, ref = scene
    with store.connection() as db:
        db.execute("CREATE TABLE observer_probe(value TEXT)")
    records, acquired, reads, rasters = [], [], [], []
    original_read, original_render = service._composition_asset, carousel.render_svg
    original_verify, injected_verify_wait = carousel.verify_image, 0.02

    def read(actor, ident):
        reads.append(ident)
        return original_read(actor, ident)

    def render(*args, **kwargs):
        rasters.append(True)
        return original_render(*args, **kwargs)

    def verify(*args, **kwargs):
        time.sleep(injected_verify_wait)
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(carousel, "verify_image", verify)
    monkeypatch.setattr(service, "_composition_asset", read)
    monkeypatch.setattr(carousel, "render_svg", render)

    class Observer(logging.Handler):
        def emit(self, record):
            records.append(record)
            observer = sqlite3.connect(store.path, timeout=0, isolation_level=None)
            try:
                observer.execute("BEGIN IMMEDIATE")
                observer.execute("INSERT INTO observer_probe VALUES('after release')")
                observer.commit()
                acquired.append(True)
            finally:
                observer.close()
            raise RuntimeError("private failing observer")

    logger = logging.getLogger("social_operations.carousel")
    handler, previous_level = Observer(), logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        first = service.command(actor, {"command": command, "request_key": "private-export-one"})
        second = service.command(actor, {"command": command, "request_key": "private-export-two"})
        before_replay = inventory(store)

        def unexpected_render(*args, **kwargs):
            pytest.fail("Immediate replay rendered again")

        monkeypatch.setattr(service, "_render", unexpected_render)
        replay = service.command(actor, {"command": command, "request_key": "private-export-one"})
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    assert receipt_without_cursor(replay) == receipt_without_cursor(first)
    assert inventory(store) == before_replay
    assert first["cards"] == second["cards"] and first["media"] == second["media"]
    assert reads == [ref, ref] and rasters == [True]
    assert acquired == [True, True] and len(records) == 2
    source_bytes = len(app.read_asset(actor, ref)[0])
    verified_bytes = 0
    for index, card in enumerate(first["cards"]):
        data, mime, _ = app.read_asset(actor, card["asset_ref"])
        verified_bytes += len(data)
        assert mime == "image/png" and (card["width"], card["height"]) == (128, 160)
        with Image.open(io.BytesIO(data)) as image:
            assert image.size == (128, 160) and image.getpixel((50, 50)) == (23, 57, 87)
            assert image.getpixel((15, 15)) == ((238, 119, 0) if index < 2 else (23, 57, 87))
    stages = {"admission_wait", "admission", "resolve_validate", "cache_render",
              "slice", "verify", "persist_wait", "persist", "tx_exit", "total"}
    for cache_hit, record in enumerate(records):
        message = record.getMessage()
        event, *parts = message.split()
        fields = dict(part.split("=", 1) for part in parts)
        assert event == "carousel_export_phases" and record.exc_info is None
        assert len(message) < 2000 and "\n" not in message
        assert not any(value in message for value in ("private", ref, command["carousel_id"], str(store.path)))
        assert {name + suffix for name in stages for suffix in ("_ms", "_thread_cpu_ms")} <= fields.keys()
        assert all(int(value) >= 0 for value in fields.values())
        assert int(fields["cache_hit"]) == cache_hit and int(fields["asset_count"]) == 1
        assert int(fields["card_count"]) == 3 and int(fields["source_bytes"]) == source_bytes
        assert int(fields["verified_bytes"]) == verified_bytes
        assert int(fields["verify_ms"]) >= len(first["cards"]) * injected_verify_wait * 1000 - 1
        assert int(fields["master_bytes"]) > 0 and int(fields["slice_bytes"]) > 0
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM observer_probe").fetchone()[0] == 2


def test_export_late_replay_emits_no_false_completion(scene, monkeypatch, caplog):
    store, actor, app, service, command, _ = scene
    args = {"command": command, "request_key": "private-export-race"}
    first = service.command(actor, args)
    before = inventory(store)
    original, calls = app._replay, []

    def late_replay(*args, **kwargs):
        calls.append(True)
        return None if len(calls) == 1 else original(*args, **kwargs)

    monkeypatch.setattr(app, "_replay", late_replay)
    caplog.clear()
    assert receipt_without_cursor(service.command(actor, args)) == receipt_without_cursor(first)
    assert calls == [True, True] and inventory(store) == before
    assert not any(record.getMessage().startswith("carousel_export_phases ") for record in caplog.records)


@pytest.mark.parametrize("stage", ["render", "verify", "persist"])
def test_failed_export_preserves_error_and_has_no_completion_diagnostic(scene, monkeypatch, caplog, stage):
    store, actor, app, service, command, _ = scene
    before = inventory(store)
    failure = RuntimeError("private export failure")
    original_insert, inserts = carousel.insert_verified_image, []

    def fail(*args, **kwargs):
        raise failure

    def fail_after_insert(*args, **kwargs):
        inserts.append(True)
        if len(inserts) == 2:
            raise failure
        return original_insert(*args, **kwargs)

    if stage == "render":
        monkeypatch.setattr(service, "_render", fail)
    elif stage == "verify":
        monkeypatch.setattr(carousel, "verify_image", fail)
    else:
        monkeypatch.setattr(carousel, "insert_verified_image", fail_after_insert)
    with pytest.raises(RuntimeError) as caught:
        service.command(actor, {"command": command, "request_key": "private-export-failure"})
    assert caught.value is failure and inventory(store) == before
    assert not any(record.getMessage().startswith("carousel_export_phases ") for record in caplog.records)
