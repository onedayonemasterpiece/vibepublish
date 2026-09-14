# INC-2026-09-14-telegram-production-quarantine

Status: `Not confirmed by user` — source, rollout, observation-only recovery and
live document canary passed; user-visible Telegram confirmation remains.

## Summary

A provider-added URL entity changed an otherwise successful Telegram document
publication into `outcome_unknown`, quarantining the whole Telegram connection.
Later repair diagnostics also instantiated direct Telethon clients from the live
production session instead of using VibePublish, violating its exclusive ownership.

## Impact

The lecture-image workflow could import assets but could not add further files to
the requested Telegram topic. Repeated retries and restarts did not release the
durable connection quarantine. One browser artifact was also a site logo rather
than the described photograph; that upstream selection defect is tracked but is
not the cause of the Telegram quarantine.

## Timeline

- 2026-09-14 09:22:55Z: last fully verified target-topic publication, message 155.
- 2026-09-14 09:30:15Z: message 156 was sent as a document; Telegram recognized
  `Sakh.online` as a URL and strict readback returned
  `telegram_entities_readback_mismatch`.
- Subsequent mutations were stopped before dispatch with
  `connection_outcome_unknown`; restarts correctly preserved the safety fence.
- 2026-09-14 13:06:46Z and 13:07:05Z: two repair probes constructed separate
  `TelegramClient` instances from the production session while the production
  worker remained active. This was an operational isolation violation even though
  both probe calls returned success and a later normal MCP read remained healthy.

## Root Cause

Telegram may add or normalize entity metadata after accepting content; in this
case it added a URL entity for domain-like text. Both the adapter and the worker
required exact entity equality, so provider normalization was misclassified as
uncertain delivery. The connection-wide unknown-effect fence then behaved as
designed, but the recovery path had the same comparison and could not clear the
false unknown.

The deployment had no process-level lease for the dedicated Telegram session.
Operational diagnostics could therefore bypass the worker and open another main
MTProto client with the same StringSession. Stored-session audit found no second
copy in another environment file; the observed violation came from transient
diagnostic processes.

## Fix

- Source fixed: require exact Telegram text, target, topic and media readback;
  preserve native entity metadata as observation without making entity equality a
  delivery gate or quarantining an already completed send.
- Source fixed: add a host process lease held for the complete production worker
  lifetime and fail closed on a second conforming session owner.
- Production verified: message 156 was reconciled by observation only with its
  original operation/attempt and native identity; no resend occurred. A new image
  document was then published and read back through normal MCP/worker transport.

## Regression Checks

Focused entity-normalization, observation-only recovery, worker-finalization and
exclusive-session-owner tests pass. Relevant suites pass: adapters 81, deployment
26, runtime 171 and SDK 22. The Telegram-named suite passes 40 tests and retains
one pre-existing metadata-only download expectation failure after its publish and
document-binding assertions pass. The complete repository suite additionally
needs the missing Playwright Chromium executable and contains pre-existing
unrelated contract/version and provider-read failures.

## Release Evidence

- Release `22079838ab6a65848d1b868eca4b05833c73dbc4` activated at
  2026-09-14 13:35:16Z; rollback remains
  `276b4802325ff90181a53bd0ec08624668e03e4d`.
- Worker PID 50427 is active with zero restart-loop count and holds the production
  `telegram-session.lock` as an OS `FLOCK WRITE` lease.
- Original operation `op_3515b977342749b8ad1aa2d841ced38c` recovered to
  `verified` on Telegram message 156, topic root 5, document binding intact.
- Live canary `op_2378a9fc70d24916b17ced8aedc5111a` verified Telegram message
  157 in topic root 5 with image document hash
  `56de4ea813316e183696f0f77a35e71f16cf2709fba8b88744cbe18bc3235d9f`.
- After recovery and canary, unresolved dispatched Telegram attempt count is zero.

## Follow-Ups

- A separate owner-only Telegram media-database plane is implemented in contract
  1.6.0 with atomic staging, durable bounded retries, topic/global metadata search,
  exact provider retrieval, expiring cache and quarantine isolation. Local checks
  pass. Production release `1a944d3c639850dc8977ae216f15993313076ae5`
  migrated SQLite to version 6 and exposes all four media-database commands;
  first user-visible write confirmation is tracked in
  `docs/features/media-store/README.md` and remains `Not confirmed by user`.
- Remove direct production-session probes from repair practice and use MCP status,
  read and bounded normal-path canaries.
- Move the production credential to a separately isolated service identity/secret
  boundary. The process lease prevents a second conforming worker, but a raw
  same-user Telethon script can deliberately bypass a cooperative lock.
- Add asset-content validation so a site logo cannot be accepted as a claimed
  documentary photograph without explicit review.
