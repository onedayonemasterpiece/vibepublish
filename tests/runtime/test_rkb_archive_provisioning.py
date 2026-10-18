"""No-secret operator acceptance for one-time KB technical archive identity."""
import importlib.util
import json
import sys
from pathlib import Path

from social_operations.storage import Store


def _load():
    path = Path(__file__).resolve().parents[2] / "scripts/ops/provision_rkb_archive_service.py"
    spec = importlib.util.spec_from_file_location("rkb_media_setup", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scoped_archive_provision_dry_run_apply_and_replay(tmp_path, monkeypatch, capsys):
    mod = _load()
    db_path = tmp_path / "vibe.sqlite"
    grant_path = tmp_path / "rkb-grant.json"
    store = Store(db_path)
    owner_token = store.create_principal("private", mod.OWNER, owner=True)
    owner = store.authenticate(owner_token)
    store.add_connection(owner, mod.CONNECTION, "telegram", account_type="fake")
    store.bind(owner, mod.OWNER, mod.ALIAS, mod.CONNECTION, mod.PEER)
    original = {
        "rkb_owner_id": "11111111-1111-4111-8111-111111111111",
        "client_id": "legacy-oid",
        "issuer": mod.ISSUER,
        "destination_alias": mod.ALIAS,
        "source_thread_ref": mod.THREAD_SOURCE,
        "thread_ref": mod.THREAD_IMAGES,
        "access_token": "DO_NOT_PRINT_ACCESS",
        "refresh_token": "DO_NOT_PRINT_REFRESH",
        "expires_at": 1,
    }
    grant_path.write_text(json.dumps(original))
    grant_path.chmod(0o600)
    monkeypatch.setattr(mod, "DB", db_path)
    monkeypatch.setattr(mod, "GRANT", grant_path)
    monkeypatch.setattr(sys, "argv", ["provision"])
    assert mod.main() == 0
    assert json.loads(grant_path.read_text()) == original
    with store.connection() as db:
        assert db.execute("SELECT 1 FROM principals WHERE id=?", (mod.PRINCIPAL,)).fetchone() is None
    monkeypatch.setattr(sys, "argv", ["provision", "--apply"])
    assert mod.main() == 0
    after = json.loads(grant_path.read_text())
    assert after["auth_mode"] == "local_service"
    assert after["local_endpoint"] == mod.LOOPBACK
    assert "refresh_token" not in after and "access_token" not in after
    assert after["service_token"] not in capsys.readouterr().out
    actor = store.authenticate(after["service_token"])
    assert not actor.owner
    assert actor.scopes == frozenset({"bootstrap", "status", "media.store"})
    with store.connection() as db:
        binding = store.binding(db, actor, alias=mod.ALIAS)
        assert set(json.loads(binding["rights"])) == {"publish"}
        assert store.service_media_topic_allowed(db, actor, binding, "2")
        assert store.service_media_topic_allowed(db, actor, binding, "4")
        assert not store.service_media_topic_allowed(db, actor, binding, "5")
    before = grant_path.read_bytes()
    assert mod.main() == 0
    assert grant_path.read_bytes() == before
    logs = capsys.readouterr().out
    for secret in (owner_token, after["service_token"], original["access_token"], original["refresh_token"]):
        assert secret not in logs
