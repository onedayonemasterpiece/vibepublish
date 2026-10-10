"""No real profiles or external actions; private registration and policy isolation."""
from copy import deepcopy
import json
import os
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from adapters.max.bindings import register
from adapters.max.live import RealMaxDriver, Target
from adapters.max.profile import MaxBlocked, ProfileLane
from adapters.max.live_session import private_json

EVIDENCE = dict(url="https://max.ru/channel_exact", native_id="-3", label="Exact channel",
                kind="channel", publish_verified=True, source="max_web_visible_channel")


def configured(tmp_path, lane):
    path = tmp_path / "bindings.json"
    baseline = {"account_phone": "offline-account", "targets": {
        "-1": {"alias": "Existing group", "policy": "test_group"},
        "-2": {"alias": "Scheduled channel", "policy": "scheduled_only"}}}
    path.write_text(json.dumps(baseline))
    path.chmod(0o600)
    driver = RealMaxDriver(NS(), lane,
        targets=tuple(Target(k, v["alias"], v["policy"]) for k, v in baseline["targets"].items()),
        account_check=AsyncMock(return_value=True), live_writes=True)
    driver.allowlist_path = path
    driver.binding_snapshot = deepcopy(baseline)
    driver._verified_resolution = dict(EVIDENCE)
    return driver, path, baseline


def test_private_atomic_binding_is_idempotent_and_retains_other_targets(tmp_path):
    with ProfileLane(tmp_path / "profile") as lane:
        driver, path, baseline = configured(tmp_path, lane)
        with register(driver, EVIDENCE):
            pass
        result = private_json(path)
        assert result["targets"]["-1"] == baseline["targets"]["-1"]
        assert result["targets"]["-2"] == baseline["targets"]["-2"]
        assert result["targets"]["-3"]["policy"] == "publish_channel"
        assert path.stat().st_mode & 0o777 == 0o600
        before = path.stat().st_ino
        driver._verified_resolution = dict(EVIDENCE)
        with register(driver, EVIDENCE):
            pass
        assert path.stat().st_ino == before
        assert len(driver.targets) == 3
        assert driver._verified_resolution is None


def test_runtime_binding_rolls_back_on_database_failure(tmp_path):
    with ProfileLane(tmp_path / "profile") as lane:
        driver, path, baseline = configured(tmp_path, lane)
        with pytest.raises(RuntimeError, match="ledger failure"):
            with register(driver, EVIDENCE):
                assert "-3" in driver.targets
                raise RuntimeError("ledger failure")
        assert private_json(path) == baseline
        assert "-3" not in driver.targets
        assert driver.binding_snapshot == baseline


@pytest.mark.parametrize("policy", ["test_group", "scheduled_only"])
def test_resolution_cannot_replace_existing_target_policy(tmp_path, policy):
    with ProfileLane(tmp_path / "profile") as lane:
        driver, path, baseline = configured(tmp_path, lane)
        baseline["targets"]["-3"] = {"alias": EVIDENCE["label"], "policy": policy}
        path.write_text(json.dumps(baseline))
        driver.binding_snapshot = deepcopy(baseline)
        driver.targets["-3"] = Target("-3", EVIDENCE["label"], policy)
        with pytest.raises(MaxBlocked, match="channel_binding_policy_conflict"):
            with register(driver, EVIDENCE):
                pytest.fail("policy changed")
        assert private_json(path) == baseline
        assert driver.targets["-3"].policy == policy


def test_changed_binding_document_is_never_overwritten(tmp_path):
    with ProfileLane(tmp_path / "profile") as lane:
        driver, path, baseline = configured(tmp_path, lane)
        baseline["targets"]["-4"] = {"alias": "Other", "policy": "scheduled_only"}
        path.write_text(json.dumps(baseline))
        with pytest.raises(MaxBlocked, match="binding_changed"):
            with register(driver, EVIDENCE):
                pytest.fail("changed document overwritten")
        assert private_json(path) == baseline


@pytest.mark.parametrize("unsafe", ["mode", "symlink", "directory", "unverified"])
def test_unsafe_or_unverified_registration_is_refused(tmp_path, unsafe):
    with ProfileLane(tmp_path / "profile") as lane:
        driver, path, baseline = configured(tmp_path, lane)
        if unsafe == "mode":
            path.chmod(0o644)
        elif unsafe == "symlink":
            other = tmp_path / "other.json"
            path.rename(other)
            path.symlink_to(other)
        elif unsafe == "directory":
            tmp_path.chmod(0o777)
        else:
            driver._verified_resolution = None
        try:
            with pytest.raises(MaxBlocked):
                with register(driver, EVIDENCE):
                    pytest.fail("unsafe registration")
        finally:
            tmp_path.chmod(0o700)
        if unsafe != "mode":
            assert private_json(path if unsafe != "symlink" else other) == baseline


@pytest.mark.asyncio
async def test_immediate_channel_publish_policy_does_not_grant_lifecycle_or_schedule(tmp_path):
    with ProfileLane(tmp_path / "profile") as lane:
        driver = RealMaxDriver(NS(), lane, targets=(
            Target("-1", "Group", "test_group"),
            Target("-2", "Schedule", "scheduled_only"),
            Target("-3", "Channel", "publish_channel")),
            account_check=AsyncMock(return_value=True), live_writes=True)
        await driver.mutation_preflight("-3", "publish")
        assert driver._owned_row_selector("-3") == ".messageWrapper"
        assert driver._owned_row_selector("-1") == ".messageWrapper--isOut"
        with pytest.raises(MaxBlocked, match="immediate_publication_denied"):
            await driver.mutation_preflight("-2", "publish")
        for action in ("edit", "delete", "cancel", "reschedule", "reply", "react", "forward"):
            with pytest.raises(MaxBlocked, match="channel_publish_only"):
                await driver.mutation_preflight("-3", action)
        with pytest.raises(MaxBlocked, match="channel_publish_only"):
            await driver.mutation_preflight("-3", "publish", scheduled_at="2030-01-01T10:00:00Z")
        await driver.mutation_preflight("-1", "publish")
