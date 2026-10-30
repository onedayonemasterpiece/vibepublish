"""Caption-length regression: only a verified Premium MTProto sender may exceed 1024."""
from __future__ import annotations

import math
from dataclasses import replace

import pytest

from adapters.telegram import TelegramAdapter
from social_operations.domain import DomainError, canonical, timestamp
from social_operations.network_footers import append_network_footer
from social_operations.rich_text import utf16
from tests.providers.scripted import ScriptedTL, TelegramClient, obj
from tests.providers.test_native_adapters import NOW, Journal, asset, request


TARGETS = {
    "tg_5060f37d74cf460135ee": {"provider": "telegram", "native_id": "-10055"},
    "vk_027d33367c33ba2599ee": {"provider": "vk", "native_id": "-33"},
    "max_lovekenig_announcements": {"provider": "max", "native_id": "-44"},
}


def with_footer(body, *, premium_candidate=True):
    return append_network_footer(
        "tg_5060f37d74cf460135ee", "telegram", {"text": body},
        TARGETS.get, has_media=True, telegram_user=premium_candidate,
    )


class CaptionClient(TelegramClient):
    def __init__(self, *, premium=None, config_limit=4096, exposes_flag=True):
        super().__init__()
        self.premium = premium
        self.config_limit = config_limit
        self.exposes_flag = exposes_flag

    async def get_me(self):
        result = await super().get_me()
        if self.exposes_flag:
            result.premium = self.premium
        return result

    async def __call__(self, req):
        if type(req).__name__ == "GetAppConfigRequest":
            self.calls.append(("GetAppConfigRequest", req))
            values = ([] if self.config_limit is None else [
                obj("JsonObjectValue", key="caption_length_limit_premium",
                    value=obj("JsonNumber", value=self.config_limit))
            ])
            return obj("AppConfig", config=obj("JsonObject", value=values))
        return await super().__call__(req)


def setup_caption(*, premium=None, config_limit=4096, exposes_flag=True, bot=False):
    client = CaptionClient(premium=premium, config_limit=config_limit, exposes_flag=exposes_flag)
    client.bot = bot
    adapter = TelegramAdapter(
        client, connection_id="connection", account_type="mtproto_bot" if bot else "mtproto_user",
        tl=ScriptedTL(), clock=lambda: NOW,
    )
    journal = Journal()
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail("Effect before marker")
    return adapter, client, journal


def caption_request(body, *, account_type="mtproto_user"):
    compiled = with_footer(body, premium_candidate=account_type == "mtproto_user")
    return replace(
        request("telegram"), account_type=account_type,
        content_json=canonical(compiled), assets=(asset(),),
        scheduled_at=timestamp(NOW + 3600),
    )


def test_footer_boundary_is_utf16_and_never_drops_links():
    baseline = with_footer("")
    overhead = utf16(baseline["text"])
    assert "Подписаться  ·  ВКонтакте  ·  MAX" in baseline["text"]
    ordinary = 1024 - overhead - 2  # Body + two line breaks + footer.
    assert utf16(with_footer("x" * ordinary)["text"]) == 1024
    with pytest.raises(DomainError) as blocked:
        with_footer("x" * (ordinary + 1), premium_candidate=False)
    assert blocked.value.code == "network_footer_limit"
    # Maximum candidate is admitted for MTProto users; only the worker verifies Premium.
    premium = 4096 - overhead - 2
    assert utf16(with_footer("x" * premium)["text"]) == 4096
    with pytest.raises(DomainError) as blocked:
        with_footer("x" * (premium + 1))
    assert blocked.value.code == "network_footer_limit"
    assert utf16(with_footer("😀" + "x" * (ordinary - 2))["text"]) == 1024


@pytest.mark.asyncio
async def test_premium_full_image_footer_preview_then_native_queue_readback():
    adapter, client, journal = setup_caption(premium=True, config_limit=4096.0)
    r = caption_request("А" * 1258)
    assert utf16(with_footer("А" * 1258)["text"]) > 1024
    prepared = await adapter.prepare(r, journal.hooks)
    assert prepared.capability.status == "supported"
    assert client.effects == 0 and not client.uploads  # Safe preview/preflight.
    observed = await adapter.execute(prepared, journal.hooks)
    assert observed.observed == "provider_scheduled"
    assert observed.items[0].text == with_footer("А" * 1258)["text"]
    assert observed.items[0].scheduled_at == timestamp(NOW + 3600)
    assert len(client.uploads) == 1 and client.effects == 1
    assert len([name for name, _ in client.calls if name == "GetAppConfigRequest"]) == 2
    assert len([name for name, _ in client.calls if name == "SendMediaRequest"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("premium", "exposes_flag", "config", "expected"), [
    (None, True, 4096, "provider_text_limit"),
    (False, True, 4096, "provider_text_limit"),
    (None, False, 4096, "telegram_caption_capability_unknown"),
    ("unexpected", True, 4096, "telegram_caption_capability_unknown"),
    (True, True, None, "telegram_caption_capability_unknown"),
    (True, True, math.nan, "telegram_caption_capability_unknown"),
    (True, True, 1100, "provider_text_limit"),
])
async def test_nonpremium_unknown_and_lower_server_limit_refuse_pre_effect(
    premium, exposes_flag, config, expected,
):
    adapter, client, journal = setup_caption(
        premium=premium, exposes_flag=exposes_flag, config_limit=config,
    )
    r = caption_request("А" * 1258)
    capability = await adapter.inspect(r)
    assert capability.status == "unsupported" and capability.reason == expected
    with pytest.raises(DomainError) as exc:
        await adapter.prepare(r, journal.hooks)
    assert exc.value.code == expected
    assert not client.effects and not client.uploads


@pytest.mark.asyncio
async def test_short_caption_does_not_require_premium_probe_and_bot_stays_1024():
    adapter, client, journal = setup_caption(exposes_flag=False)
    r = caption_request("А" * 70)
    assert (await adapter.prepare(r, journal.hooks)).capability.status == "supported"
    assert not any(name == "GetAppConfigRequest" for name, _ in client.calls)
    bot_adapter, bot, hooks = setup_caption(bot=True)
    rich = replace(request("telegram"), account_type="mtproto_bot",
                   content_json=canonical({"text": "А" * 1025}), assets=(asset(),))
    assert (await bot_adapter.inspect(rich)).reason == "provider_text_limit"
    assert not bot.effects


@pytest.mark.asyncio
async def test_premium_revocation_between_prepare_and_execute_refuses_without_upload():
    adapter, client, journal = setup_caption(premium=True)
    r = caption_request("А" * 1258)
    prepared = await adapter.prepare(r, journal.hooks)
    client.premium = None
    with pytest.raises(DomainError) as exc:
        await adapter.execute(prepared, journal.hooks)
    assert exc.value.code == "provider_text_limit"
    assert not client.uploads and not client.effects


@pytest.mark.asyncio
async def test_readback_does_not_reject_completed_send_after_premium_change():
    adapter, client, journal = setup_caption(premium=True)
    r = caption_request("А" * 1258)
    prepared = await adapter.prepare(r, journal.hooks)
    client.after_mutation = lambda _: setattr(client, "premium", None)
    result = await adapter.execute(prepared, journal.hooks)
    assert result.observed == "provider_scheduled"
    assert result.items[0].text == with_footer("А" * 1258)["text"]
    assert client.effects == 1
