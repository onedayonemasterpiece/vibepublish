# INC-2026-10-11-known-vk-effect-and-edit-recovery

Status: `Open` — fixes `Not confirmed by user`. Historical early-morning evidence is retained below; later cargo carousel acceptance and unresolved transport follow-ups are recorded in the continuation.

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

Verify the legitimate owner grant, in-place Telegram caption edit preserving media/time, old exact-effect reconciliation without a duplicate post, and the revised VK intent through the supported public tools after an authorized release. At the early-morning snapshot, HTTP transport discarded non-200 status/body; do not infer a more specific cause from those historical vk_http_failed receipts.

## Cargo carousel continuation and verified outcome (17:35 UTC)

The later cargo repair concerned the existing [community post 168](https://vk.ru/wall-241261191_168), publication `pub_41299892e2cd4905af1bc70554f34d53`. It must not be conflated with the earlier scheduled-publication evidence above.

- PR #73 (main `58e2b9ef150fc029734cf57f81971fb9d6e7e402`) aligned bounded multi-photo execution and command budgets after three saved photos and cancellation of the fourth at the former 90-second outer cap. Explicit upload HTTP 502/504 remained a separate failure.
- Revision 10, operation `op_d46aba9366ad4468aeb9bb4ea578d619`, attempt `attempt_cc5eb1662b874979945102f0f3cbd877`, retained four saved-photo receipts from its first preparation. Its later single permitted recovery failed on image three with HTTP 504 at approximately 3.976/4.035/4.020 seconds, although the same frozen image had previously received HTTP 200 in 14.044 seconds. No wall edit occurred in those failures. This does not establish a size limit or identify the failing upstream gateway.
- PR #74 (main `17eada3e9d5c2373ab4150198f4843a86b8f0394`) resolved only a durably proven video allocation followed by local URL rejection before upload. Reconciliation of `op_470cf07b5adb46d4a04ebf8fa0863793` retained its allocation, dispatch history and retry prohibition; unrelated carousel work became eligible. Video publication itself was not repaired or replayed.
- PR #75 (main `0997dd173e44058f88ec00f47117666176f28d41`, deployed source `ee589789a35bce28986a521ea2c35689cfab2c02`) added authority-bound saved-prefix reuse. Its additional photos.getById prerequisite returned HTTP 200 followed by VK error code 200 on revision 12. The ledger retained only generic vk_api_failed, so exact credential/permission cause and error_msg cannot be reconstructed.
- PR #76 removed that additional prerequisite and used authoritative saveWallPhoto receipts through the normal attachment path. Fresh native CAS and ordered provider-byte fingerprints, dimensions and target-owner verification remained mandatory. Local checks: 93 focused tests; 986 aggregate tests plus 238 subtests. Both CI runs [38159026066](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/38159026066) and [38159049866](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/38159049866) passed. Main `c49560138d734d27048cd8cd72acc062745de178` exactly matched deployed source `3384b39237e2407a61aa3704aaa734d6a2c76d14`; both services and health were verified at 17:34 UTC.
- The one unused revision-12 recovery of `op_500b690174c2456f98f8df51573641a3`, attempt `attempt_1089c298bc81446a917ae7eefe52c5a3`, reused all four photos with zero new uploads. wall.edit succeeded once at 17:35:09 UTC; terminal verified/edited followed at 17:35:20 UTC. Saved provider_binding readback targets exactly post -241261191_168 with ordered photos photo-241261191_457239157, photo-241261191_457239158, photo-241261191_457239159 and photo-241261191_457239160. The separate observed_media list is empty; evidence is the verified provider binding, not an invented second observation list.

The carousel publication outcome is verified. General repair status remains Not confirmed by user. Upload HTTP 502/504 root cause and video upload-URL rejection remain unresolved; successful receipt reuse is not proof those transport failures were cured.

### Historical lessons checked

EventsBot incidents [27 August](https://github.com/onedayonemasterpiece/events-bot-new/blob/main/docs/reports/incidents/INC-2026-08-27-eventsbot-vk-image-publish-outcome-unknown.md), [30 August](https://github.com/onedayonemasterpiece/events-bot-new/blob/main/docs/reports/incidents/INC-2026-08-30-mcp-scheduled-readback-routing.md), [24 September](https://github.com/onedayonemasterpiece/events-bot-new/blob/main/docs/reports/incidents/INC-2026-09-24-vk-afisha-publication-recurrence.md) and [27 September](https://github.com/onedayonemasterpiece/events-bot-new/blob/main/docs/reports/incidents/INC-2026-09-27-vk-auto-video-reader-publisher-token.md) were reviewed. Vibe already reads bounded compressed receipts to EOF, so that historical defect does not explain explicit 502/504. VK photo owner/ID reassignment requires the existing stronger ordered byte/dimension/owner proof, never count-only acceptance. A historical JPEG-quality fix concerned HTTP200/empty-photo and is not evidence for further compression here. Reader failures must not trigger a silent global fallback to publishing credentials.

The remaining logging correction must preserve bounded host/phase/wire-byte/response-identifier evidence without signed URLs, raw bodies, credentials or arbitrary provider text. The earlier 7 October incident's sanitized-error follow-up was not sufficient to answer this recurrence; do not close that observability gap merely because one post succeeded.
