"""W3 regression tests: URL replay, bounded image ingress, and read-only final status."""
from __future__ import annotations

import asyncio
import io
import json
import random
import sqlite3

import pytest
from PIL import Image

from adapters.fake import FakeProvider
from social_operations.asset_ingress import upload_image
from social_operations.assets import (
    INGRESS_IMAGE_MAX_BYTES, VERIFIED_IMAGE_MAX_BYTES, verify_image,
)
from social_operations.domain import DomainError
from social_operations.ingress import IngressApplication, PublicImage
from social_operations.storage import Store
from social_operations.worker import Worker


def image_bytes(mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, (3, 2), (200, 70, 10, 128) if mode == "RGBA" else (200, 70, 10)).save(out, "PNG")
    return out.getvalue()


def setup(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    for name in ("telegram", "vk"):
        store.add_connection(actor, "conn_" + name, name, account_type="fake", shared=True)
        store.bind(actor, "owner", name, "conn_" + name, "target_" + name)
    return store, actor


@pytest.mark.asyncio
async def test_https_replay_survives_expired_or_changed_source_without_fetch(tmp_path):
    store, actor = setup(tmp_path)
    fetched = []
    async def original_fetch(url):
        fetched.append(url)
        return PublicImage(image_bytes(), "image/png", url)

    app = IngressApplication(store, fetcher=original_fetch)
    args = {
        "to": ["telegram"], "content": {"text": "A tram"},
        "media": [{"source": {"kind": "url", "url": "https://images.example.test/a.png"}}],
        "request_key": "same-https-operation",
    }
    first = await app.call(actor, "vibepublish_publish", args)
    assert first["state"] == "accepted", first

    async def unavailable(url):
        raise AssertionError("replay must not refetch an expired or changed URL")

    restarted = IngressApplication(Store(store.path), fetcher=unavailable)
    again = await restarted.call(actor, "vibepublish_publish", args)
    assert again["operation_id"] == first["operation_id"]
    altered_url = {**args, "media": [{"source": {"kind": "url", "url": "https://images.example.test/now-different.png"}}]}
    again = await restarted.call(actor, "vibepublish_publish", altered_url)
    assert again["operation_id"] == first["operation_id"]
    wrong_text = {**args, "content": {"text": "Different"}}
    assert (await restarted.call(actor, "vibepublish_publish", wrong_text))["error"]["code"] == "idempotency_conflict"
    assert fetched == [args["media"][0]["source"]["url"]]
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM operations WHERE action='publish'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 2


def test_transparent_png_is_composited_over_white():
    image = Image.new("RGBA", (2, 1))
    image.putpixel((0, 0), (255, 0, 0, 0))
    image.putpixel((1, 0), (255, 0, 0, 128))
    stream = io.BytesIO()
    image.save(stream, "PNG")
    clean = verify_image(stream.getvalue(), "image/png")
    assert clean.mime == "image/png"
    with Image.open(io.BytesIO(clean.data)) as actual:
        assert actual.mode == "RGB"
        assert actual.getpixel((0, 0)) == (255, 255, 255)
        assert actual.getpixel((1, 0)) == (255, 127, 127)


def test_image_limit_is_identical_before_decode_and_after_sanitization(tmp_path, monkeypatch):
    assert INGRESS_IMAGE_MAX_BYTES == VERIFIED_IMAGE_MAX_BYTES == 20 * 1024 * 1024
    oversized = b"x" * (INGRESS_IMAGE_MAX_BYTES + 1)
    with pytest.raises(DomainError, match="20 MiB") as caught:
        verify_image(oversized, "image/png")
    assert caught.value.code == "asset_size_limit"
    store, actor = setup(tmp_path)
    with pytest.raises(DomainError, match="20 MiB") as caught:
        upload_image(type("Service", (), {"store": store})(), actor, oversized, "image/png", "large-image")
    assert caught.value.code == "asset_size_limit"
    assert "Document" not in caught.value.message

    # If neither cleaned PNG nor quality-92 JPEG fits the configured budget,
    # fail during sanitization rather than at provider dispatch.
    source = Image.effect_noise((128, 128), 70).convert("RGB")
    stream = io.BytesIO()
    source.save(stream, "JPEG", quality=80)
    limit = len(stream.getvalue()) + 128
    monkeypatch.setattr("social_operations.assets.VERIFIED_IMAGE_MAX_BYTES", limit)
    with pytest.raises(DomainError, match="Sanitized image") as caught:
        verify_image(stream.getvalue(), "image/jpeg", max_input_bytes=limit)
    assert caught.value.code == "asset_size_limit"


@pytest.mark.asyncio
async def test_status_waits_for_slow_second_network_without_new_cursor(tmp_path):
    store, actor = setup(tmp_path)
    app = IngressApplication(store)
    providers = {name: FakeProvider(tmp_path / "remote.sqlite", name) for name in ("telegram", "vk")}
    providers["vk"].gate = asyncio.Event()
    accepted = await app.call(actor, "vibepublish_publish", {
        "to": ["telegram", "vk"], "content": {"text": "Each network independently"},
        "request_key": "long-status",
    })
    assert "operation_id" in accepted, accepted
    running = asyncio.create_task(Worker(store, providers).run_once())
    try:
        async with asyncio.timeout(5):
            while providers["telegram"].count("effect") == 0:
                await asyncio.sleep(0.02)
        with store.connection() as db:
            before = db.execute("SELECT count(*) FROM cursors").fetchone()[0]
        # A concurrent write lock would make the old receipt's BEGIN IMMEDIATE
        # block. Summary reads must work without trying to acquire that lock.
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                partial = await asyncio.wait_for(app.call(actor, "vibepublish_status", {
                    "ids": [accepted["operation_id"]], "wait_final": True, "wait_seconds": 1,
                }), timeout=3)
            finally:
                db.rollback()
        progress = partial["receipts"][0]["summary"]
        assert progress["result"] == "выполняется"
        assert {n["provider"]: n["status"] for n in progress["networks"]} == {
            "telegram": "готово", "vk": "выполняется"}
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM cursors").fetchone()[0] == before
    finally:
        providers["vk"].gate.set()
        await running
    final = await app.call(actor, "vibepublish_status", {
        "ids": [accepted["operation_id"]], "wait_final": True, "wait_seconds": 1,
    })
    receipt = final["receipts"][0]
    assert receipt["operation_complete"]
    assert receipt["summary"]["result"] == "доставлено во все сети"
    assert all(row["status"] == "готово" for row in receipt["summary"]["networks"])
    assert providers["telegram"].count("effect") == providers["vk"].count("effect") == 1


@pytest.mark.asyncio
async def test_terminal_vk_refusal_preserves_telegram_success(tmp_path):
    store, actor = setup(tmp_path)
    class RefusingVK(FakeProvider):
        async def execute(self, prepared, hooks):
            self.record("execute", prepared.request.attempt_id)
            raise DomainError("needs_auth", "VK authorization expired")

    providers = {
        "telegram": FakeProvider(tmp_path / "remote.sqlite", "telegram"),
        "vk": RefusingVK(tmp_path / "remote.sqlite", "vk"),
    }
    app = IngressApplication(store)
    accepted = await app.call(actor, "vibepublish_publish", {
        "to": ["telegram", "vk"], "content": {"text": "Delivery is independent"},
        "request_key": "refusal-no-rollback",
    })
    await Worker(store, providers).run_once()
    snapshot = (await app.call(actor, "vibepublish_status", {
        "ids": [accepted["operation_id"]], "wait_final": True, "wait_seconds": 1,
    }))["receipts"][0]
    statuses = {n["provider"]: n for n in snapshot["summary"]["networks"]}
    assert statuses["telegram"]["status"] == "готово"
    assert statuses["vk"]["status"] == "отказ"
    assert statuses["vk"]["reason"] == "Нет действующей авторизации сети"
    assert snapshot["summary"]["result"] == "доставлено в 1 из 2"
    assert providers["telegram"].count("effect") == 1
    assert providers["vk"].count("effect") == 0


@pytest.mark.asyncio
async def test_status_formats_next_attempt_in_tenant_time_without_cursor(tmp_path):
    store, actor = setup(tmp_path)
    app = IngressApplication(store)
    accepted = await app.call(actor, "vibepublish_publish", {
        "to": ["vk"], "content": {"text": "Retry shown"},
        "request_key": "pending-retry",
    })
    with store.tx() as db:
        db.execute("UPDATE operations SET result=? WHERE id=?", (
            '{"vk_completion_retry_at":"2026-10-27T14:05:00Z"}',
            accepted["operation_id"],
        ))
    snapshot = (await app.call(actor, "vibepublish_status", {
        "ids": [accepted["operation_id"]],
    }))["receipts"][0]
    vk = snapshot["summary"]["networks"][0]
    assert vk["status"] == "выполняется"
    assert vk["next_attempt_at"] == "2026-10-27T14:05:00Z"
    assert vk["next_attempt_time"] == "16:05"



@pytest.mark.asyncio
async def test_phone_jpeg_png_expansion_uses_jpeg_and_publishes_to_tg_vk(tmp_path):
    # Deterministic full-color sensor noise: JPEG fits, sanitized PNG cannot.
    width, height = 4000, 3000
    pixels = random.Random(20261027).randbytes(width * height * 3)
    phone = Image.frombytes("RGB", (width, height), pixels)
    source_stream = io.BytesIO()
    phone.save(source_stream, format="JPEG", quality=82)
    source = source_stream.getvalue()
    assert len(source) < INGRESS_IMAGE_MAX_BYTES
    png_stream = io.BytesIO()
    phone.save(png_stream, format="PNG")
    assert len(png_stream.getvalue()) > VERIFIED_IMAGE_MAX_BYTES

    store, actor = setup(tmp_path)
    app = IngressApplication(store)
    ingress_receipt = upload_image(app, actor, source, "image/jpeg", "phone-jpeg")
    assert ingress_receipt["mime"] == "image/jpeg"
    asset_id = ingress_receipt["asset_id"]
    derivative, actual_mime, _ = app.read_asset(actor, asset_id)
    assert actual_mime == "image/jpeg"
    assert len(derivative) <= VERIFIED_IMAGE_MAX_BYTES
    with Image.open(io.BytesIO(derivative)) as decoded:
        assert decoded.format == "JPEG"
        assert decoded.size == (width, height)

    # HTTPS import must reuse the JPEG derivative, not assume a PNG MIME.
    urls = []
    async def fake_fetch(url):
        urls.append(url)
        return PublicImage(source, "image/jpeg", url)
    public = IngressApplication(store, fetcher=fake_fetch)
    assert await public._import_url(actor, "https://images.example.test/phone.jpg") == asset_id
    assert len(urls) == 1

    accepted = await app.call(actor, "vibepublish_publish", {
        "to": ["telegram", "vk"],
        "content": {"text": "Phone photo"},
        "media": [{"source": {"kind": "asset", "id": asset_id}}],
        "request_key": "phone-to-two-networks",
    })
    assert accepted["state"] == "accepted", accepted
    with store.connection() as db:
        plans = [json.loads(row["plan"]) for row in db.execute(
            "SELECT plan FROM attempts WHERE operation_id=?", (accepted["operation_id"],))]
    assert len(plans) == 2
    assert all(plan["assets"][0]["mime"] == "image/jpeg" for plan in plans)

    providers = {network: FakeProvider(tmp_path / "remote.sqlite", network)
                 for network in ("telegram", "vk")}
    await Worker(store, providers).run_once()
    final = (await app.call(actor, "vibepublish_status", {
        "ids": [accepted["operation_id"]], "wait_final": True, "wait_seconds": 1,
    }))["receipts"][0]
    assert final["operation_complete"], final
    assert final["summary"]["result"] == "доставлено во все сети"
    assert providers["telegram"].count("effect") == 1
    assert providers["vk"].count("effect") == 1
