# INC-2026-10-30-telegram-premium-caption

Status: `Open — code fix pending GitHub CI and deployment`

## Summary
The owner's "Тигр в комнате" Telegram photo post could not reach preview: `network_footer_limit`. The original includes one image, about 1258 characters, and an automatic cross-channel footer. VK was independently queued successfully; never repeat it.

## Impact
Telegram "Полюбить Калининград Анонсы" was **not scheduled** for 2026-11-01 10:30 Kaliningrad (08:30 UTC). There is no evidence of a Telegram send. Existing VK operation `op_0891374570ff4b2185eddab31d7e18f2` and publication `pub_e8ff69837c7542f89df03f6139a68099` must not be re-created.

## Timeline
- 2026-10-30: Owner reports Telegram preview refusal and requests Premium-capability investigation.
- 2026-10-30: Confirmed production transport Telethon 1.44 MTProto **user**, not Bot API. The live session's Premium flag is not exposed via existing public capabilities; do not infer it.
- 2026-10-30: Located hard-coded 1024 in `social_operations/network_footers.py` and `social_operations/rich_text.py`; followed all inspect/prepare/execute/custom-emoji/readback consumers.

## Root Cause
The synchronous plan/footer compiler applied the ordinary 1024-character photo-caption limit to every Telegram connection. Separately, the MTProto adapter applied the same static limit on every image caption. Neither consulted the authenticated sending account's Premium flag or the server-side `caption_length_limit_premium`. A premature refusal prevented provider preflight.

## Fix
Only MTProto **user** post+media plans may carry a **candidate** caption up to 4096 including the preserved footer. `TelegramAdapter` checks its own `get_me().premium` and Telegram `help.getAppConfig` in preview/prepare and again before upload/send. Missing or unverified Premium capability explicitly blocks. Non-Premium and bots keep ordinary 1024. Readback of an already-created native post is not invalidated by later Premium changes. No changes to secrets, sessions, permissions, DB schema, Telegram/VK send flows or footer links.

## Regression Checks
`tests/providers/test_telegram_premium_caption.py`, `tests/runtime/test_network_footers.py`; full GitHub CI Python 3.12 and 3.13 pending. Tests cover exact length boundaries, UTF-16, one image+footer, preflight no effects, known/non/unknown Premium, live config refusal, revocation between prepare and execute, and readback after send.

## Release Evidence
Source PR/merge and CI run receipts will be linked upon verification. **Not installed** until an independently authorized release action; a merge cannot prove that the running worker or server was updated. Live Premium state and the complete original-post preview remain unverified until the existing worker session is queried after rollout.

## Follow-Ups
dot will perform only the Telegram preview of the full original with its image after verified deployment and will schedule Telegram once if supported. The existing VK queue is untouched. If Premium is unknown/non-Premium, do not drop footer or silently split the post; return a clear refusal and ask the owner for the editorial alternative.
