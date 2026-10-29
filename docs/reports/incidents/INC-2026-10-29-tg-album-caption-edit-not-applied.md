# INC-2026-10-29-tg-album-caption-edit-not-applied

Status: `Open` (tool fixed and deployed; owner requirement not applied to the published post)

## Summary

Owner required the open tickets URL in the scheduled Telegram album «Плетёный муж»
(Полюбить Калининград, 29.10 10:30 Kaliningrad = 08:30 UTC) to be hidden under the word «Билеты».
VibePublish refused the edit twice (two separate defects). Both were fixed and deployed by
07:46 UTC, 44 minutes before publication, but the executor (dot) made no further VibePublish
call. The post went out with the open URL.

## Impact

- Telegram post https://t.me/c/2331532485/5399 published with an open URL instead of «Билеты».
- Native forward to kraftmarket39 (done later by dot) copied the same caption.
- VK post unaffected (owner requirement was Telegram-only).

## Timeline (UTC, 29.10.2026)

- 03:28:29 — dot: `publication_update` edit, op_c2ec963685024cfab25e5e1afc71405d (revision 2).
  Telegram refused before dispatch: `telegram_album_edit_needs_review` (adapter refused every album edit).
  Nothing sent; TG applied_revision=1.
- 06:24 — owner opens coordination thread; dot hands over the album edit.
- 06:46 — PR #105 deployed (9122569): text-only album edit allowed.
- 07:34 — dot retries; VibePublish refuses at admission `selected_target_not_verified`
  (the undispatched revision-2 refusal was treated as the Telegram head). No operation created.
- 07:46 — PR #106 deployed (0097951): a refusal that sent nothing no longer blocks the edit.
  dot told in the coordination thread to repeat the edit.
- 07:57 — dot (social-publish thread): «попытку снова отклонила проверка разрешения».
  Evidence (owner-connector read, 08:50): no publication_update/edit operation exists after 07:46.
  The refusal came from dot's own permission check, before any VibePublish call; no error code reported.
- 08:30 — post published with the open URL.
- 08:4x — owner: «оформляй инцидент». dot instructed to edit the published post now.

## Root Cause

1. VibePublish: Telegram adapter refused every album edit (`telegram_album_edit_needs_review`), a
   manual-review state forbidden by the product rules. Fixed in PR #105.
2. VibePublish: scoped edit took a pre-dispatch refusal as the target head
   (`selected_target_not_verified`). Fixed in PR #106.
3. Execution: after the fix the executor did not call the tool again; its own permission check
   stopped the action although the owner's requirement was explicit. No operation id or error code
   was reported, and the controller (Claude) did not drive the edit to completion before 08:30.

## Fix

- PR #105, PR #106 (deployed, regression tests added).
- Published post: dot instructed to apply the same edit to the published item.

## Regression Checks

- tests/providers/test_telegram_hydrated_edit.py::test_album_caption_edit_keeps_every_photo
- tests/runtime/test_managed_item_media_edits.py::test_scoped_edit_after_refusal_without_send_edits_last_applied_item

## Release Evidence

- 9122569 (PR #105) 06:46 UTC, 0097951 (PR #106) 07:46 UTC; ancestor check against the running
  release read from the process cmdline; MCP endpoint answered 401 (auth required) after restart.

## Follow-Ups

- Executor: after a tool fix, repeat the owner-required action immediately and report operation id
  or the exact refusal with its origin (own check vs VibePublish).
- Controller: when a fix unblocks a time-bound owner requirement, confirm the effect on the provider
  before the deadline instead of only notifying.
- Close when the published post shows «Билеты» (provider read) or the owner waives it.
