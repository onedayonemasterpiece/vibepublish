# INC-2026-09-12-telegram-p0-zombie-worker

Status: `Open` — source mitigation is `Not confirmed by user` until DevCoveer rollout/live acceptance.

## Summary

A live Telegram P0 run exposed an unhealthy MTProto client that remained attached to a running worker after the transport disconnected. Later jobs could still be claimed even though Telegram RPC readiness was no longer valid. The same run also exposed fragile numeric peer/access-hash resolution for the bound group used by topic `/5`.

## Impact

The target scenario `public HTTPS image -> private VibePublish asset -> Telegram document -> exact topic /5 provider confirmation/readback -> private media bytes` could fail before provider effect. Generic worker/preflight errors obscured the concrete transport stage and exception class. No source-level evidence justifies calling the live runtime healthy until rollout acceptance is rerun.

## Timeline

- 2026-09-12: live P0 failure reported; disconnected MTProto transport and entity-resolution gaps identified.
- 2026-09-12: source hardening implemented on `work/vibepublish-core-20260904` without changing existing `thread_ref`, document-role or readback semantics.
- 2026-09-12: first focused CI exposed an HTTPS-ingress idempotency edge case where byte-identical source and sanitized PNG rows could yield different asset IDs.
- 2026-09-12: canonical asset selection fixed; focused Telegram P0 gates passed on Python 3.12 and 3.13.

## Root Cause

The native Telegram wiring disabled Telethon auto-reconnect but the adapter did not independently check connection liveness before RPCs. Peer lookup relied on the client's entity cache/direct resolution and did not generically hydrate access hashes from the account dialogs for active bindings. Unexpected exceptions could fall through generic worker/preflight failure codes. Public URL media had no bounded server-side image ingress. The initial ingress implementation also returned a non-canonical asset ID when source and sanitized PNG bytes were identical, destabilizing request identity on replay.

## Fix

- Health-check/reconnect before Telegram RPCs and revalidate authorization after reconnect.
- Never retry a Telegram mutation after the RPC has started; existing outcome-unknown/idempotency ownership is preserved.
- Hydrate exact numeric peers from active connection bindings/dialogs and cache the resolved entity.
- Emit sanitized `exception_type`, `stage` and `correlation_id` diagnostics without provider/session exception text.
- Report runtime-health failures as temporarily unavailable rather than supported.
- Add public-HTTPS-only image ingress with scope/schema-first admission, public-IP DNS validation/pinning, bounded redirects/body/media types and existing image sanitization into private assets.
- Canonicalize equivalent private asset rows so request-key replay stays stable.

## Regression Checks

Focused CI covers reconnect, entity hydration for `-1004379835477`, exact topic root `5`, `role=document`, provider confirmation and document-byte readback, public-HTTPS rejection boundaries, safe diagnostics, request-key replay and private asset access. The dedicated source gate runs `git diff --check`, focused pytest, compileall and imports on Python 3.12 and 3.13.

## Release Evidence

Source commits are on `work/vibepublish-core-20260904`. Focused Telegram P0 source gates are green on both Python versions. This is source/CI evidence only; no DevCoveer rollout or live Telegram mutation/readback is claimed by this record yet.

## Follow-Ups

- Roll out the exact final source SHA to the existing DevCoveer runtime without creating a new venv/runtime.
- Re-run the exact topic `/5` live acceptance including public HTTPS import, document send, provider confirmation, topic-scoped readback and private media resource bytes.
- Close this incident only after live acceptance evidence confirms reconnect/entity hydration and no duplicate send behavior.
