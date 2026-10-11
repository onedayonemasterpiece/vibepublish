"""Offline proof-checked reuse never uploads again or bypasses native CAS."""
import copy
import json
from dataclasses import replace

import pytest

from adapters.vk import VKAdapter
from social_operations.domain import DomainError, canonical
from tests.providers.test_native_adapters import Journal, NOW, asset, request
from tests.providers.test_vk_photo_copy_binding import Copies


class SavedPhotos(Copies):
    def __init__(self):
        super().__init__()
        self.read_failure = None

    async def invoke(self, **args):
        if args["method"] != "photos.getById":
            return await super().invoke(**args)
        self.calls.append((args["method"], args["role"], copy.deepcopy(args["params"])))
        assert args["role"] == "reader"
        if self.read_failure == "transport":
            raise OSError("fixture photo read failed")
        values = args["params"]["photos"]
        values = values if isinstance(values, (tuple, list)) else values.split(",")
        rows = []
        for value in values:
            owner, ident = map(int, str(value).split("_")[:2])
            photo = self.photos.get(ident)
            if photo is not None and photo["owner_id"] == owner:
                rows.append(copy.deepcopy(photo))
        if self.read_failure == "missing":
            rows.pop()
        elif self.read_failure == "reorder":
            rows.reverse()
        elif self.read_failure == "wrong_id":
            rows[0]["id"] += 1
        elif self.read_failure == "bytes":
            self.blobs[rows[0]["sizes"][0]["url"]] = asset(9).data
        return rows


async def staged_edit(count=4):
    transport = SavedPhotos()
    adapter = VKAdapter(transport, connection_id="connection", clock=lambda: NOW)
    initial = request("vk", content_json=canonical({"text": "Original"}))
    first = Journal()
    remote = (await adapter.execute(await adapter.prepare(initial, first.hooks), first.hooks)).items[0]
    source = request("vk", operation_id="op_source", attempt_id="attempt_source",
                     plan_digest="b" * 64, action="edit", existing=remote,
                     content_json=canonical({"text": "Four authorized photos"}),
                     assets=tuple(asset(n) for n in range(1, count + 1)), deadline=NOW + 630)
    blocked = Journal()
    blocked.fail_before = True
    with pytest.raises(DomainError) as error:
        await adapter.execute(await adapter.prepare(source, blocked.hooks), blocked.hooks)
    assert error.value.code == "access_revoked"
    assert len(transport.uploads) == count and transport.effects == 1
    transition, checkpoint = blocked.checkpoints[-1]
    assert transition == "vk_prepared"
    staging = {
        "media": checkpoint["media"], "photo_proofs": checkpoint["photo_proofs"],
        "source_attempt_id": source.attempt_id, "source_plan_digest": source.plan_digest,
        "target": source.native_target, "post_id": source.existing.native_id,
        "asset_hashes": [item.sha256 for item in source.assets],
    }
    new = replace(source, operation_id="op_new_authorized", attempt_id="attempt_new_authorized",
                  plan_digest="c" * 64)
    return adapter, transport, new, staging, blocked


async def prepared_reuse(adapter, request_value, staging, journal):
    prepared = await adapter.prepare(request_value, journal.hooks)
    state = json.loads(prepared.state_json)
    state["staged_photos"] = copy.deepcopy(staging)
    return replace(prepared, state_json=canonical(state))


def mutations(calls):
    return [method for method, _, _ in calls if method in
            {"photos.getWallUploadServer", "upload_photo", "photos.saveWallPhoto",
             "wall.post", "wall.edit", "wall.delete"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2, 4, 10])
@pytest.mark.parametrize("reordered", [False, True])
async def test_reuses_exact_saved_ids_in_approved_order_without_upload_or_save(count, reordered):
    adapter, transport, current, staging, blocked = await staged_edit(count)
    if reordered:
        transport.read_failure = "reorder"
    journal = Journal()
    start = len(transport.calls)
    prepared = await prepared_reuse(adapter, current, staging, journal)
    observation = await adapter.execute(prepared, journal.hooks)
    calls = transport.calls[start:]
    assert mutations(calls) == ["wall.edit"]
    assert len(transport.uploads) == count and transport.effects == 2
    assert observation.items[0].native_id == current.existing.native_id
    assert observation.items[0].media_hashes == tuple(item.sha256 for item in current.assets)
    assert observation.items[0].provider_media == tuple(
        "photo-101_" + str(int(value.split("_")[1]) + 10000) for value in staging["media"])
    read = [params["photos"] for method, _, params in calls if method == "photos.getById"]
    assert len(read) == 1
    values = read[0] if isinstance(read[0], (tuple, list)) else read[0].split(",")
    assert list(values) == [value.removeprefix("photo") for value in staging["media"]]
    assert len(journal.markers) == 1 and not blocked.markers
    assert "private_fixture_key" not in journal.checkpoint_json


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "missing", "wrong_id", "bytes"])
async def test_saved_photo_read_or_proof_failure_never_falls_back_to_upload(failure):
    adapter, transport, current, staging, _ = await staged_edit()
    journal = Journal()
    prepared = await prepared_reuse(adapter, current, staging, journal)
    transport.read_failure = failure
    start = len(transport.calls)
    with pytest.raises((DomainError, OSError)):
        await adapter.execute(prepared, journal.hooks)
    assert mutations(transport.calls[start:]) == []
    assert len(transport.uploads) == 4 and transport.effects == 1
    assert not journal.markers


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("target", "-202"), ("post_id", "999"), ("asset_hashes", ["0" * 64] * 4),
    ("media", []), ("photo_proofs", []),
])
async def test_staging_bound_to_exact_target_post_and_ordered_assets(field, value):
    adapter, transport, current, staging, _ = await staged_edit()
    staging[field] = value
    journal = Journal()
    prepared = await prepared_reuse(adapter, current, staging, journal)
    start = len(transport.calls)
    with pytest.raises(DomainError):
        await adapter.execute(prepared, journal.hooks)
    assert mutations(transport.calls[start:]) == []
    assert len(transport.uploads) == 4 and transport.effects == 1
    assert not journal.markers


@pytest.mark.asyncio
async def test_native_cas_change_after_prepare_blocks_before_readback_or_wall_mutation():
    adapter, transport, current, staging, _ = await staged_edit()
    journal = Journal()
    prepared = await prepared_reuse(adapter, current, staging, journal)
    transport.posts[(int(current.native_target), int(current.existing.native_id))]["text"] = "External edit"
    start = len(transport.calls)
    with pytest.raises(DomainError) as error:
        await adapter.execute(prepared, journal.hooks)
    assert error.value.code == "remote_revision_conflict"
    assert mutations(transport.calls[start:]) == []
    assert not any(method == "photos.getById" for method, _, _ in transport.calls[start:])
    assert len(transport.uploads) == 4 and transport.effects == 1
    assert not journal.markers


@pytest.mark.asyncio
async def test_native_change_during_photo_verification_is_caught_by_final_cas():
    adapter, transport, current, staging, _ = await staged_edit()
    journal = Journal()
    prepared = await prepared_reuse(adapter, current, staging, journal)
    fingerprint = transport.image_fingerprint
    async def change_during_read(url):
        proof = await fingerprint(url)
        transport.posts[(int(current.native_target), int(current.existing.native_id))]["text"] = "Changed during verification"
        return proof
    transport.image_fingerprint = change_during_read
    start = len(transport.calls)
    with pytest.raises(DomainError) as error:
        await adapter.execute(prepared, journal.hooks)
    assert error.value.code == "remote_revision_conflict"
    assert any(method == "photos.getById" for method, _, _ in transport.calls[start:])
    assert mutations(transport.calls[start:]) == []
    assert len(transport.uploads) == 4 and transport.effects == 1
    assert not journal.markers


@pytest.mark.asyncio
async def test_verified_prefix_is_checked_before_only_remaining_suffix_uploads():
    adapter, transport, current, staging, _ = await staged_edit()
    staging["media"] = staging["media"][:2]
    staging["photo_proofs"] = staging["photo_proofs"][:2]
    journal = Journal()
    prepared = await prepared_reuse(adapter, current, staging, journal)
    start = len(transport.calls)
    observation = await adapter.execute(prepared, journal.hooks)
    calls = transport.calls[start:]
    methods = [method for method, _, _ in calls]
    assert methods.index("photos.getById") < methods.index("upload_photo")
    assert methods.count("upload_photo") == methods.count("photos.saveWallPhoto") == 2
    assert len(transport.uploads) == 6 and transport.effects == 2
    assert observation.items[0].provider_media[:2] == ("photo-101_11001", "photo-101_11002")
    prefixes = [cp for phase, cp in journal.checkpoints if phase == "vk_photo_staging"]
    assert [len(cp["media"]) for cp in prefixes][-2:] == [3, 4]
    assert all(cp["media"][:2] == staging["media"] for cp in prefixes)
    assert all(cp["photo_proofs"][:2] == staging["photo_proofs"] for cp in prefixes)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "wrong_id", "bytes", "transport"])
async def test_entire_prefix_must_verify_before_any_suffix_upload(failure):
    adapter, transport, current, staging, _ = await staged_edit()
    staging["media"] = staging["media"][:2]
    staging["photo_proofs"] = staging["photo_proofs"][:2]
    journal = Journal()
    prepared = await prepared_reuse(adapter, current, staging, journal)
    transport.read_failure = failure
    start = len(transport.calls)
    with pytest.raises((DomainError, OSError)):
        await adapter.execute(prepared, journal.hooks)
    assert mutations(transport.calls[start:]) == []
    assert len(transport.uploads) == 4 and transport.effects == 1


@pytest.mark.asyncio
async def test_different_authorized_assets_without_selected_staging_upload_normally():
    adapter, transport, current, staging, _ = await staged_edit()
    current = replace(current, assets=tuple(asset(n) for n in range(5, 9)))
    journal = Journal()
    prepared = await adapter.prepare(current, journal.hooks)
    start = len(transport.calls)
    observation = await adapter.execute(prepared, journal.hooks)
    calls = transport.calls[start:]
    assert sum(method == "upload_photo" for method, _, _ in calls) == 4
    assert not any(method == "photos.getById" for method, _, _ in calls)
    assert observation.items[0].media_hashes == tuple(a.sha256 for a in current.assets)
    assert len(transport.uploads) == 8 and transport.effects == 2
