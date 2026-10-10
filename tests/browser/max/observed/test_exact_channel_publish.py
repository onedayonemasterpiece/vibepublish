"""Synthetic browser replay of immediate channel posts. Never live acceptance."""
import asyncio
import base64
import hashlib

import pytest

from adapters.max.live import Target
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer, effects

pytestmark = pytest.mark.asyncio

IMAGE = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==")
TEXT = "News digest: Details"
ENTITIES = [dict(type="text_link", offset=13, length=7, url="https://example.com/event")]


async def test_named_link_and_photo_channel_without_isout_has_one_causal_send_and_recovery(writer):
    driver, page, state, hooks = writer
    driver.targets["-202"] = Target("-202", "Channel A", "publish_channel")
    driver.live_writes = True
    driver.timeout = 30
    async def slow_preparation(name):
        if name == "MAX_PREPARED":
            await asyncio.sleep(2)
    state["after_checkpoint"] = slow_preparation
    # Provider channel objects lack the account-outgoing marker by design.
    state["fault"] = "foreign"
    try:
        result = await driver.submit_plain_candidate(target="-202", text=TEXT,
            entities=ENTITIES, media=(dict(name="0.png", mimeType="image/png", buffer=IMAGE),),
            attempt_id="attempt", plan_digest="plan", hooks=hooks)
    except MaxBlocked as error:
        raise AssertionError({"checkpoints": [name for name, _ in state["checkpoints"]],
                              "effects": len(effects(state)),
                              "cause_type": type(error.__context__).__name__}) from error.__context__
    assert result["item"]["target"] == "-202"
    assert result["item"]["entities"] == ENTITIES
    assert result["item"]["observed_media"][0]["sha256"] == hashlib.sha256(IMAGE).hexdigest()
    assert len(effects(state)) == 1
    assert state["messages"][0]["outgoing"] is False
    names = [name for name, _ in state["checkpoints"]]
    assert names == ["MAX_PREPARED", "MAX_NATIVE_REFERENCE", "MAX_NATIVE_REFERENCE", "MAX_CANDIDATE_OBSERVED"]
    assert state["checkpoints"][1][1]["recovery_reference"] == "https://max.ru/c/-202/provider-item"
    recovery = await driver._reconcile_dom(state["checkpoints"][-1][1])
    assert recovery["item"]["id"] == "provider-item"
    assert recovery["item"]["entities"] == ENTITIES
    assert recovery["item"]["observed_media"] == result["item"]["observed_media"]
    assert recovery["quarantine_released"] is False
    assert len(effects(state)) == 1
    with pytest.raises(MaxBlocked, match="outcome_unknown"):
        await driver.submit_plain_candidate(target="-202", text=TEXT, entities=ENTITIES,
            media=(), attempt_id="another", plan_digest="another", hooks=hooks)
    assert len(effects(state)) == 1


async def test_channel_readback_deadline_preserves_native_receipt_and_never_resends(writer):
    driver, _, state, hooks = writer
    driver.targets["-202"] = Target("-202", "Channel A", "publish_channel")
    driver.live_writes = True
    driver.timeout = 20
    state["fault"] = "foreign"
    async def expire_after_reference(name):
        if name == "MAX_PREPARED":
            await asyncio.sleep(2)
        if name == "MAX_NATIVE_REFERENCE":
            await asyncio.sleep(driver.timeout + 1)
    state["after_checkpoint"] = expire_after_reference
    with pytest.raises(MaxBlocked, match="outcome_unknown") as failure:
        await driver.submit_plain_candidate(target="-202", text=TEXT,
            entities=ENTITIES, attempt_id="attempt", plan_digest="plan", hooks=hooks)
    assert isinstance(failure.value.__context__, TimeoutError)
    references = [saved for name, saved in state["checkpoints"] if name == "MAX_NATIVE_REFERENCE"]
    assert references and references[0]["native_id"] == "provider-item"
    assert references[0]["recovery_reference"] == "https://max.ru/c/-202/provider-item"
    assert driver.lane.marker.exists()
    assert len(effects(state)) == 1
    with pytest.raises(MaxBlocked, match="outcome_unknown"):
        await driver.submit_plain_candidate(target="-202", text=TEXT,
            entities=ENTITIES, attempt_id="attempt-new", plan_digest="plan-new", hooks=hooks)
    assert len(effects(state)) == 1


async def test_named_link_group_still_rejects_foreign_outgoing_candidate(writer):
    driver, _, state, hooks = writer
    state["fault"] = "foreign"
    with pytest.raises(MaxBlocked, match="outcome_unknown"):
        await driver.submit_plain_candidate(target="-101", text=TEXT,
            entities=ENTITIES, attempt_id="attempt", plan_digest="plan", hooks=hooks)
    assert len(effects(state)) == 1
    assert driver.lane.marker.exists()
    assert not [checkpoint for checkpoint in state["checkpoints"] if checkpoint[0] == "MAX_NATIVE_REFERENCE"]
