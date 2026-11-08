"""Slow phase diagnostics observe real transactions after their writer is released."""
import asyncio
from contextlib import contextmanager
import logging
import sqlite3
import time

import pytest

from social_operations.carousel import CarouselService
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


@pytest.mark.parametrize("path", ["maintenance", "saved_miss", "saved_hit"])
def test_phase_warning_is_after_release_private_and_cannot_change_commit(tmp_path, monkeypatch, path):
    now = 1_800_000_000
    store = Store(tmp_path / "private-ledger.sqlite", clock=lambda: now)
    actor = store.authenticate(store.create_principal("private-tenant", "private-owner", owner=True))
    app = Application(store)
    service = CarouselService(app)
    created = service.command(actor, {"command": {"kind": "create", "brief": "Private phase fixture",
        "card_count": 3, "card_width": 128, "card_height": 160,
        "svg": '<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
               '<rect width="384" height="160" fill="#173957"/></svg>'},
        "request_key": "private-create-key"})
    command = {"command": {"kind": "render", "carousel_id": created["carousel_id"],
        "revision": 1, "view": "region", "region": [10, 20, 80, 70],
        "scale": 1, "save_asset": True}}
    if path == "saved_hit":
        service.command(actor, command)
    with store.connection() as db:
        before_assets = db.execute("SELECT count(*) FROM assets").fetchone()[0]
        db.execute("CREATE TABLE private_observer_probe(value TEXT)")

    # Keep the actual production SQL/body; delay the selected SQL under its real writer.
    target = ("FROM assets INDEXED BY assets_retention_lookup" if path == "maintenance"
              else "SELECT id,bytes FROM assets")
    delays = []
    def trace(sql):
        if target in sql:
            delays.append(True)
            time.sleep(1.02)

    connection = store.connection
    @contextmanager
    def traced_connection():
        with connection() as db:
            db.set_trace_callback(trace)
            yield db
    monkeypatch.setattr(store, "connection", traced_connection)

    records, acquired, observed_deadlines = [], [], []
    class Observer(logging.Handler):
        def emit(self, record):
            records.append(record)
            observer = sqlite3.connect(store.path, timeout=0, isolation_level=None)
            try:
                observer.execute("BEGIN IMMEDIATE")
                observer.execute("INSERT INTO private_observer_probe VALUES('committed observer')")
                observer.commit()
                acquired.append(True)
                if path == "maintenance":
                    observed_deadlines.append(store.next_media_store_purge)
            finally:
                observer.close()
            raise RuntimeError("private failing observer")

    logger = logging.getLogger("social_operations.worker" if path == "maintenance"
                               else "social_operations.carousel")
    handler = Observer()
    previous_level = logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        if path == "maintenance":
            assert asyncio.run(Worker(store).run_once()) is False
            assert store.next_media_store_purge == now + 60
        else:
            preview = service.command(actor, command)
            data, mime, _ = app.read_asset(actor, preview.metadata["asset_ref"])
            assert data == preview.data and mime == "image/png"
            journal = service.command(actor, {"command": {"kind": "get", "scope": "journal",
                "carousel_id": created["carousel_id"]}})["journal"]
            assert any(row.get("asset_ref") == preview.metadata["asset_ref"]
                       and row.get("revision") == 1 for row in journal)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    assert delays == [True] and acquired == [True] and len(records) == 1
    if path == "maintenance":
        assert observed_deadlines == [now + 60]
    record = records[0]
    assert record.levelno == logging.WARNING and record.exc_info is None
    event, *parts = record.getMessage().split()
    fields = dict(part.split("=", 1) for part in parts)
    assert int(fields["elapsed_ms"]) >= 1000
    if path == "maintenance":
        assert event == "sqlite_maintenance_phases"
        assert set(fields) == {"elapsed_ms", "expire_ms", "cache_purge_ms",
                              "retention_ms", "reclaim_ms", "tx_exit_ms"}
        assert int(fields["retention_ms"]) >= 1000
    else:
        assert event == "sqlite_saved_asset_phases"
        assert set(fields) == {"elapsed_ms", "authority_ms", "asset_total_ms", "hash_ms",
                              "dedup_ms", "quota_ms", "insert_bytes_ms", "journal_ms", "tx_exit_ms"}
        assert int(fields["dedup_ms"]) >= 1000
        if path == "saved_hit":
            assert fields["quota_ms"] == fields["insert_bytes_ms"] == "not_run"
        else:
            assert int(fields["quota_ms"]) >= 0 and int(fields["insert_bytes_ms"]) >= 0
    assert all(value == "not_run" or int(value) >= 0 for value in fields.values())
    assert "private" not in record.getMessage()
    assert created["carousel_id"] not in record.getMessage()
    assert str(tmp_path) not in record.getMessage()
    with store.connection() as db:
        expected_delta = 2 if path == "saved_miss" else 0
        assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == before_assets + expected_delta
        assert db.execute("SELECT count(*) FROM private_observer_probe").fetchone()[0] == 1
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
