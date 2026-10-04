"""Actual ledger/worker admission, mixed workloads, restart and rolling windows."""
import asyncio
import json

import pytest

from tests.runtime.test_media_store import Provider, args, png
from social_operations.assets import insert_verified_image, verify_image
from social_operations.domain import DomainError
from social_operations.media_budget import media_files
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


def admissions(store, connection=None):
    with store.connection() as db:
        if connection:
            rows = db.execute(
                "SELECT connection_id,attempt_id,media_count,admitted_at "
                "FROM telegram_media_admissions WHERE connection_id=? "
                "ORDER BY admitted_at,id",
                (connection,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT connection_id,attempt_id,media_count,admitted_at "
                "FROM telegram_media_admissions ORDER BY admitted_at,id"
            ).fetchall()
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_27_files_shared_budget_durable_defer_restart_and_independent_connection(tmp_path):
    clock = [1800000000.0]
    store = Store(tmp_path / "ledger.sqlite", clock=lambda: clock[0])
    actor = store.authenticate(store.create_principal("t", "owner", owner=True))
    for connection, alias in [
        ("connection", "vault"),
        ("connection", "ordinary"),
        ("other_connection", "other"),
    ]:
        if alias != "ordinary":
            store.add_connection(actor, connection, "telegram", account_type="fake")
        store.bind(
            actor,
            "owner",
            alias,
            connection,
            {
                "vault": "-1004379835477",
                "ordinary": "-1004379835499",
                "other": "-1004379835478",
            }[alias],
        )
    with store.tx() as db:
        asset = insert_verified_image(store, db, actor, verify_image(png(), "image/png"))

    provider = Provider()
    app = Application(store)
    workers = [
        Worker(store, {"telegram": provider}),
        Worker(Store(store.path, clock=lambda: clock[0]), {"telegram": provider}),
    ]

    accepted = []
    for i in range(25):
        result = await app.call(
            actor,
            "vibepublish_media_store",
            args(asset, f"budget-{i}", text=f"Budget synthetic file {i}"),
        )
        assert "operation_id" in result, result
        accepted.append(result)
    album = await app.call(
        actor,
        "vibepublish_publish",
        {
            "to": ["ordinary"],
            "content": {"text": "Ordinary album shares the same connection"},
            "media": [
                {"source": {"kind": "asset", "id": asset}, "role": "document"},
                {"source": {"kind": "asset", "id": asset}, "role": "document"},
            ],
            "request_key": "ordinary-album",
        },
    )
    assert "operation_id" in album, album
    accepted.append(album)
    text_only = await app.call(
        actor,
        "vibepublish_publish",
        {
            "to": ["ordinary"],
            "content": {"text": "Text only unaffected"},
            "request_key": "text-only",
        },
    )
    other = await app.call(
        actor,
        "vibepublish_publish",
        {
            "to": ["other"],
            "content": {"text": "Independent connection"},
            "media": [
                {"source": {"kind": "asset", "id": asset}, "role": "document"},
                {"source": {"kind": "asset", "id": asset}, "role": "document"},
                {"source": {"kind": "asset", "id": asset}, "role": "document"},
            ],
            "request_key": "other-connection",
        },
    )

    for _ in range(40):
        await asyncio.gather(*(worker.run_once() for worker in workers))

    first = admissions(store)
    assert sum(row["media_count"] for row in first if row["connection_id"] == "connection") == 20
    assert sum(row["media_count"] for row in first if row["connection_id"] == "other_connection") == 3
    assert store.receipt(actor, text_only["operation_id"])["state"] == "verified"
    assert store.receipt(actor, other["operation_id"])["state"] == "verified"

    with store.connection() as db:
        waiting = list(db.execute(
            "SELECT a.* FROM attempts a "
            "WHERE a.state='accepted' AND a.stage='waiting_connection'"
        ))
        assert waiting
        assert all(row["dispatched"] == 0 for row in waiting)
        assert all(
            db.execute(
                "SELECT complete FROM operations WHERE id=?",
                (row["operation_id"],),
            ).fetchone()["complete"] == 0
            for row in waiting
        )
        for row in waiting:
            operation = db.execute(
                "SELECT deadline,lease_until FROM operations WHERE id=?",
                (row["operation_id"],),
            ).fetchone()
            assert operation["deadline"] >= operation["lease_until"] + 120

    # A restarted worker sees the same durable admission window and due time.
    store = Store(store.path, clock=lambda: clock[0])
    worker = Worker(store, {"telegram": provider})
    clock[0] += 59.999
    assert not await worker.run_once()
    assert admissions(store) == first

    clock[0] = 1800000060.002
    for _ in range(40):
        if not await worker.run_once():
            break

    assert all(store.receipt(actor, result["operation_id"])["state"] == "verified" for result in accepted)
    all_admissions = admissions(store)
    assert sum(
        row["media_count"] for row in all_admissions
        if row["connection_id"] == "connection"
    ) == 27

    expanded = [
        (row["admitted_at"], row["connection_id"])
        for row in all_admissions
        for _ in range(row["media_count"])
    ]
    for right_edge, connection in expanded:
        assert sum(
            1
            for observed, observed_connection in expanded
            if observed_connection == connection
            and right_edge - 60.0 < observed <= right_edge
        ) <= 20

    # Deterministic evidence is inspectable and replay never creates a duplicate.
    (tmp_path / "admission-evidence.json").write_text(
        json.dumps(all_admissions, sort_keys=True)
    )
    before = provider.effects
    for i in range(25):
        replay = await app.call(
            actor,
            "vibepublish_media_store",
            args(asset, f"budget-{i}", text=f"Budget synthetic file {i}"),
        )
        assert replay["operation_id"] == accepted[i]["operation_id"]
    assert not await worker.run_once()
    assert provider.effects == before


class UploadThenCooldownProvider(Provider):
    def __init__(self):
        super().__init__()
        self.uploaded_files = 0

    async def execute(self, prepared, hooks):
        self.uploaded_files += len(prepared.request.assets)
        raise DomainError("telegram_cooldown")


@pytest.mark.asyncio
async def test_failed_predispatch_uploads_still_consume_budget(tmp_path):
    clock = [1800000000.0]
    store = Store(tmp_path / "failed-upload.sqlite", clock=lambda: clock[0])
    actor = store.authenticate(store.create_principal("t", "owner", owner=True))
    store.add_connection(actor, "connection", "telegram", account_type="fake")
    store.bind(actor, "owner", "vault", "connection", "-1004379835477")
    with store.tx() as db:
        asset = insert_verified_image(store, db, actor, verify_image(png(), "image/png"))

    provider = UploadThenCooldownProvider()
    app = Application(store)
    worker = Worker(store, {"telegram": provider})
    results = [
        await app.call(
            actor,
            "vibepublish_media_store",
            args(asset, f"failed-{i}", text=f"Failed upload {i}"),
        )
        for i in range(21)
    ]

    for _ in range(21):
        assert await worker.run_once()

    assert provider.uploaded_files == 20
    assert sum(row["media_count"] for row in admissions(store, "connection")) == 20
    last = store.receipt(actor, results[-1]["operation_id"])
    assert last["state"] == "running"
    assert last["deliveries"][0]["stage"] == "waiting_connection"
    assert last["deliveries"][0]["observed"] == "not_attempted"


def test_media_upload_count_includes_changed_edits_and_excludes_native_forwards():
    assert media_files({"action": "forward", "assets": [{"sha256": "a"}]}) == 0
    assert media_files(
        {
            "action": "edit",
            "assets": [{"sha256": "a"}],
            "existing": {"media_hashes": ["a"]},
        }
    ) == 0
    assert media_files(
        {
            "action": "edit",
            "assets": [{"sha256": "b"}],
            "existing": {"media_hashes": ["a"]},
        }
    ) == 1
