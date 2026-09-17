# INC-2026-09-12-telegram-p0-zombie-worker

Status: `Open` — source mitigation is `Not confirmed by user` until DevCoveer rollout/live acceptance.

## Summary

A live Telegram P0 run exposed an unhealthy MTProto client that remained attached to a running worker after the transport disconnected. Later jobs could still be claimed even though Telegram RPC readiness was no longer valid. Follow-up review also found that the first source mitigation overfit direct topic links to already registered destination bindings instead of treating the pasted Telegram link as the owner's target selector.

## Impact

The target scenario `public HTTPS image -> private VibePublish asset -> Telegram document -> exact topic provider confirmation/readback -> private media bytes` could fail before provider effect. Generic worker/preflight errors obscured the concrete transport stage and exception class. In addition, an owner could not reliably paste an arbitrary accessible `/c/<chat>/<topic>` link unless that exact chat had already been registered in VibePublish. No source-level evidence justifies calling the live runtime healthy until rollout acceptance is rerun.

## Timeline

- 2026-09-12: live P0 failure reported; disconnected MTProto transport and entity-resolution gaps identified.
- 2026-09-12: source hardening implemented on `work/vibepublish-core-20260904` without changing existing document-role or readback semantics.
- 2026-09-12: first focused CI exposed an HTTPS-ingress idempotency edge case where byte-identical source and sanitized PNG rows could yield different asset IDs.
- 2026-09-12: canonical asset selection fixed; focused Telegram P0 gates passed on Python 3.12 and 3.13.
- 2026-09-12: owner review identified an overfit in topic routing: numeric peer `-1004379835477` was only a parsed example, but the implementation still required the corresponding chat to be pre-bound.
- 2026-09-12: direct owner topic routing corrected so arbitrary accessible `/c/<chat>/<topic>` links derive peer/topic dynamically; partner binding boundaries remain unchanged.

## Root Cause

The native Telegram wiring disabled Telethon auto-reconnect but the adapter did not independently check connection liveness before RPCs. Peer lookup relied on the client's entity cache/direct resolution and initially hydrated only peers captured from bindings at worker startup. The service also interpreted `thread_ref` through an existing destination binding, effectively turning a concrete example chat ID into a routing prerequisite. Unexpected exceptions could fall through generic worker/preflight failure codes. Public URL media had no bounded server-side image ingress. The initial ingress implementation also returned a non-canonical asset ID when source and sanitized PNG bytes were identical, destabilizing request identity on replay.

## Fix

- Health-check/reconnect before Telegram RPCs and revalidate authorization after reconnect.
- Never retry a Telegram mutation after the RPC has started; existing outcome-unknown/idempotency ownership is preserved.
- Treat an owner `/c/<chat>/<topic>` link as the concrete target. Derive the numeric Telegram peer and topic root per request; no chat number is special.
- Materialize owner direct-link targets as hidden internal routes so existing immutable plan/recovery/item-ref machinery remains intact; do not expose them as ordinary destination aliases or expand partner grants.
- If one Telegram connection is active, the owner link alone selects the chat. With multiple Telegram connections, an existing Telegram alias selects only the account connection; the pasted link still selects the actual chat/topic.
- Hydrate a requested numeric peer from authenticated account dialogs even when that peer was not present when the worker started.
- Emit sanitized `exception_type`, `stage` and `correlation_id` diagnostics without provider/session exception text.
- Report runtime-health failures as temporarily unavailable rather than supported.
- Add public-HTTPS-only image ingress with scope/schema-first admission, public-IP DNS validation/pinning, bounded redirects/body/media types and existing image sanitization into private assets.
- Canonicalize equivalent private asset rows so request-key replay stays stable.

## Regression Checks

Focused CI covers reconnect, post-start entity hydration for multiple distinct Telegram peers, two distinct `/c/<chat>/<topic>` targets, owner publish/read without pre-created chat bindings, multi-account ambiguity, partner binding isolation, `role=document`, provider confirmation/readback, public-HTTPS rejection boundaries, safe diagnostics, request-key replay and private asset access. The dedicated source gate runs `git diff --check`, focused pytest, compileall and imports on Python 3.12 and 3.13.

## Release Evidence

Source commits are on `work/vibepublish-core-20260904`. Focused Telegram P0 source gates must be green on both Python versions. This is source/CI evidence only; no DevCoveer rollout or live Telegram mutation/readback is claimed by this record yet.

## Follow-Ups

- Roll out the exact final source SHA to the existing DevCoveer runtime without creating a new venv/runtime.
- Re-run live acceptance against at least two real accessible Telegram chats/topics, not only `/c/4379835477/5`, including public HTTPS import, document send, provider confirmation, topic-scoped readback and private media resource bytes.
- Close this incident only after live acceptance evidence confirms generic target resolution, reconnect/entity hydration and no duplicate send behavior.
