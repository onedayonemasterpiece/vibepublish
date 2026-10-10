"""Production split-lane routing for admitted exact destination discovery."""
import pytest

from social_operations.service import Application
from social_operations.worker import Worker
from tests.runtime.test_max_destination_resolution import Adapter, URL, setup


async def admit(store, owner, key="split-lane-max-resolution"):
    result = await Application(store).call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "max", "url": URL},
        "request_key": key})
    assert result["state"] == "accepted", result
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("ordinary_connections", [("telegram", "vk"), ()])
async def test_split_max_resolve_belongs_only_to_owned_max_lane(tmp_path, ordinary_connections):
    store, owner, _ = setup(tmp_path)
    result = await admit(store, owner)
    adapter = Adapter()
    ordinary = Worker(store, {}, worker_id="ordinary",
        connection_ids=ordinary_connections, include_unrouted=True)
    max_worker = Worker(store, {"conn": adapter}, worker_id="max-worker",
        connection_ids=("conn",), include_unrouted=False)
    # Exact resolution has no attempts or binding yet, but is not unrouted.
    assert await ordinary.run_once() is False
    assert adapter.calls == 0
    with store.connection() as db:
        pending = db.execute("SELECT state,lease_owner FROM operations WHERE id=?",
                             (result["operation_id"],)).fetchone()
        assert tuple(pending) == ("accepted", None)
    assert await max_worker.run_once() is True
    done = store.receipt(owner, result["operation_id"])
    assert done["state"] == "verified", done
    assert adapter.calls == 1 and adapter.registrations == 1
    assert await ordinary.run_once() is False
    assert await max_worker.run_once() is False


@pytest.mark.asyncio
async def test_expired_max_resolve_lease_remains_in_max_lane(tmp_path):
    store, owner, _ = setup(tmp_path)
    result = await admit(store, owner)
    original = store.claim("max-lost-worker", connection_ids=("conn",),
                           include_unrouted=False)
    assert original and original["id"] == result["operation_id"]
    with store.tx() as db:
        db.execute("UPDATE operations SET lease_until=0 WHERE id=?", (original["id"],))
    assert store.claim("ordinary", connection_ids=("telegram",),
                       include_unrouted=True) is None
    recovered = store.claim("max-recovered", connection_ids=("conn",),
                            include_unrouted=False)
    assert recovered["id"] == original["id"]
    assert recovered["fence"] == original["fence"] + 1
    assert recovered["lease_owner"] == "max-recovered"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["read", "publish", "visual"])
async def test_private_connection_hint_does_not_reroute_other_action_types(tmp_path, action):
    store, owner, _ = setup(tmp_path)
    result = await admit(store, owner)
    # Simulate legacy/unrouted requests carrying unrelated metadata. The new
    # routing hint is trusted only for the admitted destinations action.
    with store.tx() as db:
        db.execute("UPDATE operations SET action=? WHERE id=?", (action, result["operation_id"]))
    assert store.claim("max-worker", connection_ids=("conn",),
                       include_unrouted=False) is None
    claimed = store.claim("ordinary", connection_ids=("telegram",), include_unrouted=True)
    assert claimed and claimed["id"] == result["operation_id"]


@pytest.mark.asyncio
async def test_existing_attempt_route_is_unchanged(tmp_path):
    store, owner, _ = setup(tmp_path)
    store.add_connection(owner, "telegram", "telegram", account_type="fake")
    store.bind(owner, "owner", "telegram-main", "telegram", "-111")
    result = await Application(store).call(owner, "vibepublish_publish", {
        "to": ["telegram-main"], "content": {"text": "Offline routing check"},
        "request_key": "existing-attempt-route"})
    assert result["state"] == "accepted", result
    assert store.claim("max-worker", connection_ids=("conn",),
                       include_unrouted=False) is None
    claimed = store.claim("ordinary", connection_ids=("telegram",), include_unrouted=True)
    assert claimed and claimed["id"] == result["operation_id"]
