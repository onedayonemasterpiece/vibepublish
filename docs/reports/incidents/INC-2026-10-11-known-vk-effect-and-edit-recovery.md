# INC-2026-10-11-known-vk-effect-and-edit-recovery

Status: `Open` — fixes `Not confirmed by user`; source preparation only.

## Summary

A newly imported workspace photo was successfully scheduled in Telegram, but VK stopped before dispatch because an older, exactly identified published post retained an unresolved media check. The owner then changed the new post text. The existing zero-dispatch retry correctly retained its frozen original intent, so it could not carry the new text. Telegram editing was independently denied by an explicit publish/cancel-only destination binding.

## Impact

One requested cross-provider publication is incomplete. Telegram's native schedule must be preserved. No replacement VK publication or privilege bypass is permitted. Workspace image ingress itself passed live source-hash and visual acceptance.

## Timeline

- 2026-10-11 06:07 UTC: workspace image imported and preview verified.
- 06:09–06:10 UTC: Telegram schedule verified; VK staging failed transiently three times, then succeeded; the connection fence blocked wall.post before its dispatch marker.
- 06:13 UTC: read-only database inspection confirmed zero dispatch for the new VK intent and an older exact published-post checkpoint as the connection blocker.
- 06:15 UTC: observation-only reconciliation of the older post still failed its media check. The owner requested removing a paragraph; in-place Telegram edit was denied by destination rights.
- 06:22 UTC: owner explicitly authorized persistent edit permission for the one Telegram destination. Local owner CLI lacked configured authentication; no secret extraction or grant was attempted.
- 06:25–06:28 UTC: owner authorized preparing bounded recovery and authenticated owner-administration fixes; release remains pending.

## Root Cause

Three separate domain distinctions were missing from the public workflow:

1. Known exact provider effect with unresolved media quality was classified like an unknown dispatch, quarantining unrelated destinations on the same connection. The older provider photo was visibly a horizontal crop; its 2048×886 source became 1575×886, exceeding the existing single-photo 20% crop check. Visual similarity is not sufficient to declare exact media verification.
2. A completed, never-dispatched failed child had no explicit immutable-intent replacement action. Retry cannot safely mean edit.
3. The existing authenticated owner grant domain was reachable only through local CLI credentials, not the already authenticated owner MCP actor. Partner and destination authority must remain unchanged unless explicitly granted.

## Fix

Prepare three narrow changes under the existing recovery and owner-authority domains: exact observed-effect evidence while retaining media needs-review and no-repeat protection; explicit atomic supersession of only zero-dispatch failed children; and owner-only additive edit-right grant for an exact own destination with CAS, idempotency and audit. Do not raise crop tolerances, reset dispatch markers, alter credentials, or write a replacement provider post outside the original recovery workflow.

Canonical details belong in the corresponding recovery and service-principal documentation.

## Regression Checks

Required: exact identity/text/time mismatch remains unknown; media mismatch never becomes verified; unrelated connection work is released only by valid current proof; no uncertain attempt can resend; supersession rejects dispatched/running/epoch-drifted work, retains immutable audit and never repeats successful siblings; owner grant rejects partner/foreign/stale requests and adds only edit once. Validate actual MCP schemas and integration tests, not only helper tests.

## Release Evidence

Source verification: 990 tests and 265 subtests passed across contracts, runtime, providers and visuals, including actual TCP MCP grant/supersede acceptance; pip check, compilation and git diff check passed. Two existing dependency-deprecation warnings remain. Independent local review covered authority, duplicate-send and stale-proof paths. The owner explicitly chose direct-tool work without an external coding-agent consultation. Deployment and actual publication acceptance remain pending; source-only tests do not prove them.

## Follow-Ups

Verify the legitimate owner grant, in-place Telegram caption edit preserving media/time, old exact-effect reconciliation without a duplicate post, and the revised VK intent through the supported public tools after an authorized release. HTTP transport currently discards non-200 status/body; do not infer a more specific cause from historical vk_http_failed receipts.
