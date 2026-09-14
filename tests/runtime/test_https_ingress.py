from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from social_operations.domain import DomainError
from social_operations.ingress import (
    IngressApplication,
    PublicImage,
    resolve_public_https,
)
from social_operations.storage import Store
from tests.providers.test_native_adapters import NOW

TARGET = "-1004379835477"
TOPIC_URL = "https://t.me/c/4379835477/5"
IMAGE_URL = "https://images.example.test/tram.png"


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (20, 80, 160)).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_public_https_image_becomes_private_document_asset_for_exact_topic_5():
    calls = []
    source = png_bytes()

    async def fetcher(url):
        calls.append(url)
        return PublicImage(source, "image/png", url)

    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / "ledger.sqlite", clock=lambda: NOW)
        token = store.create_principal("tenant", "owner", owner=True)
        actor = store.authenticate(token)
        store.add_connection(
            actor,
            "conn_tg",
            "telegram",
            account_type="mtproto_user",
            secret_ref="VIBEPUBLISH_TELEGRAM_SESSION",
            shared=True,
        )
        store.bind(actor, "owner", "telegram", "conn_tg", TARGET)
        app = IngressApplication(store, fetcher=fetcher)
        command = {
            "to": ["telegram"],
            "thread_ref": TOPIC_URL,
            "content": {"text": "Autonomous tram"},
            "media": [{
                "source": {"kind": "url", "url": IMAGE_URL},
                "role": "document",
            }],
            "request_key": "p0-url-document-topic-5",
        }

        accepted = await app.call(actor, "vibepublish_publish", command)
        assert accepted["state"] == "accepted", accepted
        with store.connection() as db:
            child = db.execute(
                "SELECT * FROM attempts WHERE operation_id=?",
                (accepted["operation_id"],),
            ).fetchone()
            plan = json.loads(child["plan"])
            assert plan["native_target"] == TARGET
            assert plan["topic_root_id"] == "5"
            assert plan["assets"][0]["role"] == "document"
            asset_ref = plan["assets"][0]["ref"]
            assert plan["assets"][0]["mime"] == "image/png"
            assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 2

        private_bytes, private_mime, private_sha = app.read_asset(actor, asset_ref)
        assert private_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert private_mime == "image/png"
        assert len(private_sha) == 64

        replay = await app.call(actor, "vibepublish_publish", command)
        assert replay["operation_id"] == accepted["operation_id"]
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 2
        assert calls == [IMAGE_URL, IMAGE_URL]
        assert command["media"][0]["source"] == {"kind": "url", "url": IMAGE_URL}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,code",
    [
        ("http://example.com/image.png", "image_url_invalid"),
        ("https://127.0.0.1/image.png", "image_url_not_public"),
        ("https://[::1]/image.png", "image_url_not_public"),
        ("https://localhost/image.png", "image_url_not_public"),
    ],
)
async def test_https_ingress_rejects_non_public_or_non_https_endpoints(url, code):
    with pytest.raises(DomainError) as caught:
        await resolve_public_https(url)
    assert caught.value.code == code
