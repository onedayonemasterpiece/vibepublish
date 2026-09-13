import hashlib
import json
import shutil

import pytest

from social_operations.service import Application
from social_operations.storage import Store
from tests.visuals.test_asset_ingress import png


UUID = "24a9799d-bdc7-4e68-b0ba-65150dabf4d9"
URI = f"artifact://{UUID}"
TARGET = "-1004379835477"
TOPIC_URL = "https://t.me/c/4379835477/5"


def write_artifact(
    root,
    *,
    data=None,
    mime="image/png",
    file_name="source.png",
    sha256=None,
    size=None,
    kind="image",
):
    data = png() if data is None else data
    directory = root / UUID
    directory.mkdir()
    (directory / "payload").write_bytes(data)
    actual_sha256 = hashlib.sha256(data).hexdigest()
    metadata = {
        "id": UUID,
        "uri": URI,
        "kind": kind,
        "fileName": file_name,
        "mediaType": mime,
        "size": len(data) if size is None else size,
        "sha256": actual_sha256 if sha256 is None else sha256,
        "createdAt": "2026-09-13T12:34:22.398Z",
    }
    (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return data, actual_sha256


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "browser-artifacts"
    root.mkdir()
    monkeypatch.setenv("VIBEPUBLISH_BROWSER_ARTIFACT_ROOT", str(root))
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal(
        "tenant",
        "owner",
        owner=True,
        scopes={"publish", "visual", "status"},
    )
    actor = store.authenticate(token)
    return root, store, actor, Application(store)


def command(*, uri=URI, key="browser-artifact-1"):
    return {
        "command": {"kind": "import_browser_artifact", "uri": uri},
        "request_key": key,
    }


@pytest.mark.asyncio
async def test_valid_import_preserves_original_sha_and_replays_without_source(env):
    root, store, actor, app = env
    original, original_sha256 = write_artifact(root)

    imported = await app.call(actor, "vibepublish_visual", command())
    assert imported["state"] == "verified", imported
    private_bytes, private_mime, private_sha256 = app.read_asset(actor, imported["resource_id"])
    assert private_mime == "image/png"
    assert hashlib.sha256(private_bytes).hexdigest() == private_sha256

    with store.connection() as db:
        rows = db.execute(
            "SELECT bytes,source_sha256 FROM assets ORDER BY rowid"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["bytes"] == original
    assert rows[0]["source_sha256"] == original_sha256
    assert rows[1]["source_sha256"] == original_sha256

    shutil.rmtree(root / UUID)
    replay = await Application(Store(store.path)).call(
        actor, "vibepublish_visual", command()
    )
    assert replay["operation_id"] == imported["operation_id"]
    assert replay["resource_id"] == imported["resource_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uri",
    [
        "/tmp/browser/payload",
        "artifact://../payload",
        "artifact://24a9799d-bdc7-4e68-b0ba-65150dabf4d8",
        "artifact://24a9799d-bdc7-1e68-b0ba-65150dabf4d9",
    ],
)
async def test_bad_uri_and_filesystem_path_are_rejected_by_public_contract(env, uri):
    root, _, actor, app = env
    write_artifact(root)
    result = await app.call(
        actor, "vibepublish_visual", command(uri=uri, key="bad-uri")
    )
    assert result["error"]["code"] == "invalid_input"


@pytest.mark.asyncio
async def test_nonexistent_artifact_is_rejected(env):
    _, _, actor, app = env
    result = await app.call(actor, "vibepublish_visual", command())
    assert result["error"]["code"] == "browser_artifact_not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"sha256": "0" * 64}, "browser_artifact_integrity"),
        ({"size": 1}, "browser_artifact_integrity"),
        ({"mime": "application/octet-stream"}, "browser_artifact_mime_unsupported"),
    ],
)
async def test_metadata_integrity_and_mime_are_enforced(env, change, code):
    root, _, actor, app = env
    write_artifact(root, **change)
    result = await app.call(
        actor, "vibepublish_visual", command(key=f"metadata-{code}")
    )
    assert result["error"]["code"] == code


@pytest.mark.asyncio
async def test_oversized_artifact_is_rejected_before_decode(env, monkeypatch):
    from social_operations import browser_artifact_ingress as ingress

    root, _, actor, app = env
    monkeypatch.setattr(ingress, "MAX_UPLOAD_BYTES", 100)
    write_artifact(root, data=png() + b"x" * 200)
    result = await app.call(
        actor, "vibepublish_visual", command(key="too-large")
    )
    assert result["error"]["code"] == "asset_size_limit"


@pytest.mark.asyncio
async def test_payload_symlink_is_rejected(env, tmp_path):
    root, _, actor, app = env
    source, _ = write_artifact(root)
    outside = tmp_path / "outside.png"
    outside.write_bytes(source)
    payload = root / UUID / "payload"
    payload.unlink()
    payload.symlink_to(outside)

    result = await app.call(
        actor, "vibepublish_visual", command(key="payload-symlink")
    )
    assert result["error"]["code"] == "browser_artifact_invalid"


@pytest.mark.asyncio
async def test_imported_asset_is_publishable_as_telegram_document(env):
    root, store, actor, app = env
    write_artifact(root)
    imported = await app.call(
        actor, "vibepublish_visual", command(key="publishable")
    )
    assert imported["state"] == "verified", imported

    store.add_connection(
        actor,
        "conn_tg",
        "telegram",
        account_type="mtproto_user",
        secret_ref="VIBEPUBLISH_TELEGRAM_SESSION",
        shared=True,
    )
    store.bind(actor, "owner", "telegram", "conn_tg", TARGET)
    published = await app.call(
        actor,
        "vibepublish_publish",
        {
            "to": ["telegram"],
            "thread_ref": TOPIC_URL,
            "media": [
                {
                    "source": {"kind": "asset", "id": imported["resource_id"]},
                    "role": "document",
                }
            ],
            "request_key": "browser-artifact-document",
        },
    )
    assert published["state"] == "accepted", published
    with store.connection() as db:
        plan = json.loads(
            db.execute(
                "SELECT plan FROM attempts WHERE operation_id=?",
                (published["operation_id"],),
            ).fetchone()[0]
        )
    assert plan["provider"] == "telegram"
    assert plan["native_target"] == TARGET
    assert plan["topic_root_id"] == "5"
    assert plan["assets"][0]["role"] == "document"
    assert plan["assets"][0]["ref"] == imported["resource_id"]
    assert plan["assets"][0]["mime"] == "image/png"
