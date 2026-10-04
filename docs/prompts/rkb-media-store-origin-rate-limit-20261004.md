# VibePublish — Regional Knowledge media-store mirror prerequisite

Date: 2026-10-04

This task is a narrow prerequisite for Regional Knowledge book-illustration mirroring.
Do not redesign social publishing.

## Goal

Make the existing private Telegram media store safe for durable illustration
mirrors produced by Regional Knowledge:

1. preserve immutable cross-service origin metadata;
2. enforce the owner's Telegram media budget of **no more than 20 files/images
   in any rolling 60-second window per Telegram connection/account**;
3. keep media-store put idempotent and restart-safe;
4. preserve ordinary publication isolation and unknown-outcome semantics.

Regional Knowledge remains canonical for book/page/illustration semantics and
rights. Telegram/VibePublish is only a secondary binary mirror.

## Current facts to verify first

Read current main/runtime and the canonical media-store docs.

The repository documents optional origin metadata:

- `origin.system`
- `origin.ref`
- `origin.sha256`

but the live media-store put schema observed on 2026-10-04 did not expose this
field. Verify the current runtime before changing code. If it is already fixed,
do not reimplement it.

The existing worker already has:

- one cross-process lane per provider connection;
- durable attempt state;
- request-key idempotency;
- exact provider readback;
- FloodWait/SlowMode handling;
- safe retry/reconciliation for media-store operations.

Reuse those mechanisms.

## Cross-service origin contract

For `media_store put`, support optional immutable:

~~~text
origin.system = "regional_knowledge"
origin.ref = "knowledge://illustrations/<opaque-id>"
origin.sha256 = "<64-hex crop hash>"
~~~

Requirements:

- origin never grants access or selects a destination;
- VibePublish never dereferences `origin.ref`;
- changing origin under the same request key is an idempotency conflict;
- list/search/get return the stored origin metadata;
- provider byte/hash evidence remains independently authoritative;
- no source book text, PDF, page render, bearer or object-store key is stored.

## Telegram media budget

The owner requirement is strict:

**No more than 20 outgoing Telegram files/images in any rolling 60 seconds for
one connection/account.**

This is a VibePublish/provider boundary, not a Regional Knowledge-only rule,
because multiple products can share the same Telegram connection.

Count provider media files, not just operations:

- one one-file media-store put consumes 1;
- a 10-file album/document operation consumes 10;
- any ordinary Telegram publication that uploads media consumes the same shared
  connection budget;
- text-only messages do not consume this media budget;
- native forwards that do not upload bytes do not consume it.

Do not rely only on Telegram FloodWait as the limiter. Prevent admission to the
external media effect when the rolling budget would be exceeded.

Use existing durable attempt/dispatch timestamps if sufficient. Add the smallest
durable state only if required. A worker restart must not reset the rolling
window.

When capacity is unavailable:

- do not fail/drop the media;
- do not busy-wait while holding the connection lane;
- durably defer the operation until capacity is available;
- preserve original request identity;
- never create a new request key to bypass throttling.

Provider FloodWait/SlowMode remains an independent second safety layer.

## Media-store behavior for Regional Knowledge

Regional Knowledge will send illustration crops as Telegram DOCUMENTS, not
compressed photos, and will use a stable request key derived from the canonical
illustration identity + crop hash.

Exact request replay must return the same media-store entry and must never create
another Telegram document.

## Acceptance

Do not spam the owner's real media topic merely to prove throttling.

Run a deterministic provider/runtime acceptance with **at least 25 media files**
queued closely enough to exercise the rolling budget and prove from dispatch
timestamps that every rolling 60-second interval contains <=20 files for the
same connection. Include a restart in the middle and prove the budget persists.

Also run a small real Telegram canary (1-3 tiny images/documents) in the already
authorized Regional Knowledge illustration topic provided by the caller/runtime,
then verify exact native readback, hashes, origin metadata and request replay.
Clean up only test objects when the provider contract supports safe deletion;
otherwise mark them clearly as canaries and do not create repeated duplicates.

Also prove:

- concurrent ordinary publication + media-store operations share one budget;
- text-only publication is not throttled by the media-file budget;
- two different Telegram connections do not share one budget;
- FloodWait remains recoverable;
- unknown outcome is never retried as a fresh send;
- origin mismatch under replay fails closed;
- media-store list/search/get preserve origin;
- existing public publication tests remain green.

## Do not do

- Do not make Telegram the canonical illustration store for Regional Knowledge.
- Do not add a generic scheduler.
- Do not alter MAX/VK behavior.
- Do not weaken publication unknown-outcome rules.
- Do not add AI generation or image understanding.
- Do not expose private origin metadata across owners.
- Do not increase the 20-files/60s limit.

## Deliverables

Update the media-store docs and create:

`docs/reports/rkb-media-store-origin-rate-limit-acceptance-20261004.md`

Record:

- exact main/runtime SHA;
- live schema version;
- rate-limit algorithm and durable state;
- 25+ file deterministic timing evidence;
- restart evidence;
- small real Telegram canary evidence;
- origin round-trip evidence;
- full tests/CI.

## Definition of Done

Done only when the deployed VibePublish runtime accepts immutable Regional
Knowledge origin metadata and enforces <=20 Telegram media files per rolling
60 seconds across all media-producing workloads on the same connection, with
durable defer/recovery and exact replay semantics.
