"""Offline owner-only edit grants: current authority, CAS, atomic audit and replay."""
import asyncio
from dataclasses import replace
import json
import sqlite3

import pytest
from jsonschema import Draft202012Validator

from contracts.social_mcp_v1 import catalog
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "grant.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    owner = store.authenticate(token)
    store.add_connection(owner, "tg", "telegram", account_type="fake")
    binding = store.bind(owner, "owner", "own_tg", "tg", "-100001", rights=("publish", "cancel"))
    store.bind(owner, "owner", "untouched", "tg", "-100002", rights=("publish",))
    partner_token = store.create_principal("tenant", "partner")
    store.bind(owner, "partner", "partner_tg", "tg", "-100003", rights=("publish",))
    foreign_token = store.create_principal("foreign", "foreign_owner", owner=True)
    foreign = store.authenticate(foreign_token)
    store.add_connection(foreign, "foreign_tg", "telegram", account_type="fake")
    store.bind(foreign, "foreign_owner", "foreign_alias", "foreign_tg", "-100004", rights=("publish",))
    return store, Application(store), store.authenticate(token), binding, store.authenticate(partner_token), foreign


def request(store, actor, *, key="edit-once", alias="own_tg"):
    with store.connection() as db:
        actor = store.current(db, actor)
        binding = store.binding(db, actor, alias=alias)
    return {"command": {"kind": "binding_grant_edit", "alias": alias,
                        "expected_binding_epoch": binding["epoch"],
                        "expected_routing_revision": actor.routing_revision},
            "request_key": key}


def call(app, actor, args):
    return asyncio.run(app.call(actor, "vibepublish_destinations", args))


def state(store):
    with store.connection() as db:
        return {
            "bindings": [tuple(r) for r in db.execute("SELECT id,rights,epoch,active FROM bindings ORDER BY id")],
            "principals": [tuple(r) for r in db.execute("SELECT id,scopes,owner,epoch,routing_revision,active FROM principals ORDER BY id")],
            **{table: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
               for table in ("operations", "request_keys", "events", "attempts", "publications")},
        }


def grant_kinds(app, actor):
    tool = next((t for t in app.tools(actor) if t["name"] == "vibepublish_destinations"), None)
    return set() if tool is None else {
        arm["properties"]["kind"]["const"]
        for arm in tool["inputSchema"]["properties"]["command"]["oneOf"]}


def test_exact_edit_atomic_receipt_and_idempotent_routing(setup):
    store, app, owner, binding, _, _ = setup
    args = request(store, owner)
    before = state(store)
    first = call(app, owner, args)
    assert "error" not in first
    grant = first["binding_grant"]
    assert grant["binding_id"] == binding and grant["alias"] == "own_tg" and grant["right"] == "edit"
    assert grant["before"] == {"rights": ["publish", "cancel"], "binding_epoch": 1,
                               "actor_epoch": owner.epoch, "routing_revision": owner.routing_revision}
    assert grant["after"] == {**grant["before"], "rights": ["publish", "cancel", "edit"],
                              "routing_revision": owner.routing_revision + 1}
    assert first["operation_complete"] and first["state"] == "verified"
    assert first["deliveries"] == []
    after = state(store)
    assert after["operations"] == after["request_keys"] == after["events"] == 1
    assert after["attempts"] == after["publications"] == 0
    assert [r for r in after["bindings"] if r[0] != binding] == [r for r in before["bindings"] if r[0] != binding]
    assert all(row[1:4] == before["principals"][i][1:4] for i, row in enumerate(after["principals"]))
    replay = call(app, owner, args)
    assert replay["operation_id"] == first["operation_id"] and replay["binding_grant"] == grant
    assert state(store) == after
    # A new explicit keyed request for an already held right is a no-op grant.
    second = call(app, owner, request(store, owner, key="already-held"))
    assert second["binding_grant"]["before"] == second["binding_grant"]["after"]
    with store.connection() as db:
        assert store.current(db, owner).routing_revision == owner.routing_revision + 1


@pytest.mark.parametrize("field", ["expected_binding_epoch", "expected_routing_revision"])
def test_stale_cas_has_no_effect(setup, field):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    args["command"][field] += 1
    before = state(store)
    result = call(app, owner, args)
    assert result["error"]["code"] == ("binding_epoch_conflict" if field == "expected_binding_epoch" else "routing_revision_conflict")
    assert state(store) == before


@pytest.mark.parametrize("alias", ["partner_tg", "foreign_alias", "missing"])
def test_other_principal_tenant_or_missing_alias_denied(setup, alias):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    args["command"]["alias"] = alias
    before = state(store)
    assert call(app, owner, args)["error"]["code"] == "access_denied"
    assert state(store) == before


def test_wrong_tenant_actor_denied(setup):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    before = state(store)
    assert call(app, replace(owner, tenant_id="foreign"), args)["error"]["code"] == "access_revoked"
    assert state(store) == before


def test_nonowner_hidden_and_direct_forged_actor_denied(setup):
    store, app, owner, binding, partner, _ = setup
    assert "binding_grant_edit" in grant_kinds(app, owner)
    forged = replace(partner, owner=True)
    assert "binding_grant_edit" not in grant_kinds(app, forged)
    args = request(store, partner, alias="partner_tg")
    before = state(store)
    assert call(app, forged, args)["error"]["code"] == "invalid_input"
    with pytest.raises(DomainError, match="access denied"):
        app.destinations(forged, args)
    with pytest.raises(DomainError, match="access denied"):
        store.grant_binding_rights(forged, binding, ["edit"])
    assert state(store) == before


@pytest.mark.parametrize("missing_scope", ["destinations", "publication.manage"])
def test_current_scope_required_even_when_actor_claims_it(setup, missing_scope):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    with store.tx() as db:
        db.execute("UPDATE principals SET scopes=? WHERE id=?", (json.dumps(sorted(owner.scopes - {missing_scope})), owner.principal_id))
    before = state(store)
    assert "binding_grant_edit" not in grant_kinds(app, owner)
    with pytest.raises(DomainError, match="access denied"):
        app.destinations(owner, args)
    assert state(store) == before


@pytest.mark.parametrize("mutation", [
    "UPDATE principals SET owner=0 WHERE id='owner'",
    "UPDATE principals SET active=0 WHERE id='owner'",
    "UPDATE principals SET epoch=epoch+1 WHERE id='owner'",
    "UPDATE tenants SET active=0 WHERE id='tenant'",
    "UPDATE connections SET active=0 WHERE id='tg'",
])
def test_current_authority_loss_prevents_grant(setup, mutation):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    with store.tx() as db:
        db.execute(mutation)
    before = state(store)
    with pytest.raises(DomainError):
        app.destinations(owner, args)
    assert state(store) == before


@pytest.mark.parametrize("mutation", [
    "UPDATE bindings SET epoch=epoch+1 WHERE alias='own_tg'",
    "UPDATE bindings SET active=0 WHERE alias='own_tg'",
    """UPDATE bindings SET rights='["publish","cancel"]' WHERE alias='own_tg'""",
    "UPDATE principals SET owner=0 WHERE id='owner'",
    """UPDATE principals SET scopes='["destinations"]' WHERE id='owner'""",
])
def test_key_and_status_replay_recheck_current_grant(setup, mutation):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    first = call(app, owner, args)
    assert "error" not in first
    with store.tx() as db:
        db.execute(mutation)
    before = state(store)
    with pytest.raises(DomainError):
        app.destinations(owner, args)
    with pytest.raises(DomainError):
        store.receipt(owner, first["operation_id"])
    assert state(store) == before


def test_key_replay_after_real_revocation_denied(setup):
    store, app, owner, binding, _, _ = setup
    args = request(store, owner)
    first = call(app, owner, args)
    store.revoke_binding(owner, binding)
    before = state(store)
    assert call(app, owner, args)["error"]["code"] == "access_revoked"
    with store.connection() as db:
        row = db.execute("SELECT p.*,t.timezone FROM principals p JOIN tenants t ON t.id=p.tenant_id WHERE p.id='owner'").fetchone()
        current = store.actor_row(row)
    assert "error" in call(app, current, args)
    with pytest.raises(DomainError):
        store.receipt(current, first["operation_id"])
    assert state(store) == before


def test_key_conflict_does_not_expand_another_binding(setup):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    assert "error" not in call(app, owner, args)
    before = state(store)
    other = request(store, owner, alias="untouched")
    assert call(app, owner, other)["error"]["code"] == "idempotency_conflict"
    assert state(store) == before


def test_receipt_key_failure_rolls_back_rights_revision_and_operation(setup, monkeypatch):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    before = state(store)
    def fail(*args):
        raise sqlite3.OperationalError("offline injected failure")
    monkeypatch.setattr(app, "_key", fail)
    assert call(app, owner, args)["error"]["code"] == "store_unavailable"
    assert state(store) == before


@pytest.mark.parametrize("extra", [
    {"rights": ["delete"]}, {"right": "delete"}, {"scopes": ["publish"]},
    {"principal_id": "partner"}, {"tenant_id": "foreign"}, {"binding_id": "bind_other"},
])
def test_no_arbitrary_authority_or_target_arguments(setup, extra):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    args["command"].update(extra)
    before = state(store)
    assert call(app, owner, args)["error"]["code"] == "invalid_input"
    with pytest.raises(DomainError, match="invalid input"):
        app.destinations(owner, args)
    assert state(store) == before


@pytest.mark.parametrize("field", ["request_key", "expected_binding_epoch", "expected_routing_revision"])
def test_required_request_key_and_cas(setup, field):
    store, app, owner, _, _, _ = setup
    args = request(store, owner)
    (args if field == "request_key" else args["command"]).pop(field)
    before = state(store)
    assert call(app, owner, args)["error"]["code"] == "invalid_input"
    assert state(store) == before


def test_grant_does_not_expand_sets(setup):
    store, app, owner, _, _, _ = setup
    with store.tx() as db:
        db.execute("INSERT INTO destination_sets VALUES(?,?,?,?,?,?)",
                   ("tenant", "owner", "own_set", "Own set", 1, '["own_tg"]'))
    args = request(store, owner)
    args["command"]["alias"] = "own_set"
    before = state(store)
    assert call(app, owner, args)["error"]["code"] == "access_denied"
    assert state(store) == before


def test_legacy_cli_domain_still_allows_explicit_same_tenant_grants(setup):
    store, _, owner, _, partner, foreign = setup
    with store.connection() as db:
        partner_binding = store.binding(db, partner, alias="partner_tg")["id"]
        foreign_binding = store.binding(db, foreign, alias="foreign_alias")["id"]
    assert store.grant_binding_rights(owner, partner_binding, ["edit"]) == ["publish", "edit"]
    with pytest.raises(DomainError, match="access denied"):
        store.grant_binding_rights(owner, foreign_binding, ["edit"])


def test_base_catalog_schema_stays_valid():
    for tool in catalog()["tools"]:
        Draft202012Validator.check_schema(tool["inputSchema"])
        Draft202012Validator.check_schema(tool["outputSchema"])
