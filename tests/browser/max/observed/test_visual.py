"""Same-driver visual fallback; provider calls mocked, never live credentials."""
import json
from unittest.mock import AsyncMock

import pytest
from google_ai import GoogleAIClient
from adapters.max.profile import MaxBlocked
from adapters.max.visual import VisualRecovery, visual_gateway, MODEL
from tests.browser.max.observed.test_live_navigation import recovery_setup, recovery_state, RECOVERY_TEXT

pytestmark = pytest.mark.asyncio


def setup_visual(d, monkeypatch, answer=None):
    client = visual_gateway(supabase_client=object())
    generate = AsyncMock(return_value=(json.dumps(answer or {'readable': True, 'text': RECOVERY_TEXT}), None))
    monkeypatch.setattr(client, 'generate_content_async', generate)
    record = AsyncMock()
    d.visual_recovery = VisualRecovery(client, record=record)
    return client, generate, record


async def test_default_success_never_calls_model(replay, monkeypatch):
    d, _ = await recovery_setup(replay)
    _, generate, record = setup_visual(d, monkeypatch)
    result = await d.reconcile(recovery_state())
    assert result['item']['id'] == 'new-item'
    generate.assert_not_awaited(); record.assert_not_awaited()


async def test_visual_corroboration_then_fresh_native_verification(replay, monkeypatch):
    d, page = await recovery_setup(replay)
    _, generate, record = setup_visual(d, monkeypatch)
    original = d._copy_native_reference
    calls = 0
    async def transient(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MaxBlocked('native_copy_menu_unavailable')
        return await original(*args)
    monkeypatch.setattr(d, '_copy_native_reference', transient)
    before = d.lane.marker.read_bytes()
    result = await d.reconcile(recovery_state())
    assert calls == 5  # One failed copy, then the full four-copy native verification.
    assert result['item']['id'] == 'new-item'
    assert result['visual_evidence']['exact_text_match']
    assert result['quarantine_released'] is False
    assert d.lane.marker.read_bytes() == before
    generate.assert_awaited_once(); assert record.await_count == 2
    request = generate.call_args.kwargs
    assert request['model'] == MODEL
    png = request['prompt'][1]['inline_data']['data']
    assert png.startswith(b'\x89PNG\r\n\x1a\n')
    assert record.call_args.args[0] == png
    assert record.call_args.args[1]['supplementary_only']


@pytest.mark.parametrize('failure', ['wrong_target_or_origin', 'recovery_not_outgoing',
    'recovery_native_reference_mismatch', 'recovery_attempt_mismatch', 'recovery_content_changed'])
async def test_binding_failures_never_go_to_model(replay, monkeypatch, failure):
    d, _ = await recovery_setup(replay)
    _, generate, _ = setup_visual(d, monkeypatch)
    monkeypatch.setattr(d, '_reconcile_dom', AsyncMock(side_effect=MaxBlocked(failure)))
    with pytest.raises(MaxBlocked, match=failure):
        await d.reconcile(recovery_state())
    generate.assert_not_awaited()


@pytest.mark.parametrize('answer', [dict(readable=False, text=''), dict(readable=True, text='Other post')])
async def test_visual_disagreement_cannot_become_verified(replay, monkeypatch, answer):
    d, _ = await recovery_setup(replay)
    _, generate, record = setup_visual(d, monkeypatch, answer)
    copy = AsyncMock(side_effect=MaxBlocked('native_copy_menu_unavailable'))
    monkeypatch.setattr(d, '_copy_native_reference', copy)
    with pytest.raises(MaxBlocked, match='visual_text_unconfirmed'):
        await d.reconcile(recovery_state())
    assert copy.await_count == 1
    generate.assert_awaited_once(); assert record.await_count == 2


async def test_evidence_record_failure_prevents_retry(replay, monkeypatch):
    d, _ = await recovery_setup(replay)
    _, _, record = setup_visual(d, monkeypatch)
    record.side_effect = OSError('private disk error')
    copy = AsyncMock(side_effect=MaxBlocked('native_copy_menu_unavailable'))
    monkeypatch.setattr(d, '_copy_native_reference', copy)
    with pytest.raises(MaxBlocked, match='visual_observation_unavailable'):
        await d.reconcile(recovery_state())
    assert copy.await_count == 1
    assert d.lane.marker.exists()


async def test_model_does_not_allow_infinite_dom_retries(replay, monkeypatch):
    d, _ = await recovery_setup(replay)
    _, generate, _ = setup_visual(d, monkeypatch)
    copy = AsyncMock(side_effect=MaxBlocked('native_copy_menu_unavailable'))
    monkeypatch.setattr(d, '_copy_native_reference', copy)
    with pytest.raises(MaxBlocked, match='native_copy_menu_unavailable'):
        await d.reconcile(recovery_state())
    assert copy.await_count == 2
    generate.assert_awaited_once()


async def test_shared_quota_is_mandatory():
    with pytest.raises(MaxBlocked, match='visual_shared_limiter_required'):
        visual_gateway(supabase_client=None)
    client = GoogleAIClient(supabase_client=object())
    with pytest.raises(MaxBlocked, match='visual_shared_limiter_required'):
        VisualRecovery(client, record=AsyncMock())


async def test_changed_limiter_configuration_prevents_call(replay, monkeypatch):
    d, _ = await recovery_setup(replay)
    client, generate, _ = setup_visual(d, monkeypatch)
    client.allow_local_limiter_fallback = True
    monkeypatch.setattr(d, '_copy_native_reference', AsyncMock(side_effect=MaxBlocked('native_copy_menu_unavailable')))
    with pytest.raises(MaxBlocked, match='visual_shared_limiter_required'):
        await d.reconcile(recovery_state())
    generate.assert_not_awaited()


@pytest.mark.parametrize('response', ['not JSON', '{"readable":"yes","text":"x"}',
    '{"readable":true,"text":"x","execute":"Send"}'])
async def test_malformed_model_response_keeps_capture_and_never_retries(replay, monkeypatch, response):
    d, _ = await recovery_setup(replay)
    _, generate, record = setup_visual(d, monkeypatch)
    generate.return_value = (response, None)
    copy = AsyncMock(side_effect=MaxBlocked('native_copy_menu_unavailable'))
    monkeypatch.setattr(d, '_copy_native_reference', copy)
    with pytest.raises(MaxBlocked, match='visual_invalid_response'):
        await d.reconcile(recovery_state())
    assert copy.await_count == 1
    record.assert_awaited_once()
    assert record.call_args.args[1]['phase'] == 'captured'


async def test_quota_refusal_keeps_capture_without_retry_or_provider_bypass(replay, monkeypatch):
    from google_ai import RateLimitError
    d, _ = await recovery_setup(replay)
    _, generate, record = setup_visual(d, monkeypatch)
    generate.side_effect = RateLimitError('budget exhausted')
    copy = AsyncMock(side_effect=MaxBlocked('native_copy_menu_unavailable'))
    monkeypatch.setattr(d, '_copy_native_reference', copy)
    with pytest.raises(MaxBlocked, match='visual_observation_unavailable'):
        await d.reconcile(recovery_state())
    assert copy.await_count == 1
    generate.assert_awaited_once(); record.assert_awaited_once()
    assert record.call_args.args[1]['phase'] == 'captured'
    assert d.lane.marker.exists()
