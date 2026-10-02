# Private media store

Status: `Not confirmed by user` — the reported media_store list access failure is
fixed and verified through the live MCP, pending confirmation in the user's client.
Recovery of the underlying index was verified on 2026-09-19. The active database
already had schema version 6 but an empty media index. Topic 5 now has 106 indexed
entries covering 147 verified image documents (128 distinct file hashes).
Production MCP search/get and an exact-byte import into a Wonderful Lections test
presentation passed. User acceptance in ChatGPT remains pending.

## Product boundary

The private media store is not a social publication surface. It is a single-owner
technical workflow that uses one bound private Telegram forum topic as the durable
media store while VibePublish keeps only searchable metadata and temporary staging
bytes. Public Telegram/VK/MAX publishing keeps its separate editorial,
rights, approval, scheduling and unknown-outcome policy.

## Contract

- `vibepublish_media_store put` accepts one or more already verified image assets,
  always sends them to the exact private Telegram topic as DOCUMENT, and requires
  a stable request key. It does not accept schedules, previews, forwards, edits,
  fan-out, non-Telegram targets or non-owner callers.
- `list` is text-only and scoped to one explicitly named Telegram topic. Only
  `thread_ref` is required; optional `to` must match its existing active binding.
  A mismatch is an input error, not an authorization diagnosis. The operation
  never creates bindings, grants access or contacts Telegram.
- Re-reading a media-store message without downloading bytes preserves existing
  hash evidence only when the ordered provider attachment identities and album
  membership still match. Fresh downloaded evidence replaces previous hashes.
  Changed attachments invalidate old evidence; `sha256: []` means unverified
  bytes, and `get` obtains fresh evidence.
- `search` is a global text search over every topic in the owner's indexed
  Telegram media database. Neither operation connects to Telegram or downloads
  provider media bytes. Results include caption, hashes, destination alias,
  topic link, exact message link and entry identity for duplicate detection.
- `get` downloads the exact file from Telegram by its stored chat/topic/message
  identity. Any local download copy is short-lived cache, never the durable store.
- Put bytes remain in durable local staging only until exact Telegram document
  verification. Verified staging is purged; failed/queued staging is retained so
  a provider outage cannot lose an admitted file. Unresolved staging expires one
  hour after the bounded 30-day delivery window and is purged by the worker even
  when no MCP request arrives.
- One failed/unknown media-store write never quarantines the Telegram connection,
  another media-store write, or public publication work. Public unknown attempts
  likewise do not stop the private store.
- Never-dispatched transient failures retry automatically. A dispatched attempt
  with a durable Telegram native ID is reconciled automatically by observation
  only. Retry delay is bounded and durable across worker restarts.
- Request-key replay returns the same entry/operation and never creates a duplicate.
  Exact Telegram text, topic and document binding remain required for verification;
  provider-normalized entity metadata is observational only.

## Cross-service origin metadata — 2026-10-02

Status: `Not confirmed by user` until the branch is merged and deployed.

A media-store entry may carry an optional immutable `origin` record:

```text
system   stable originating service id, e.g. regional_knowledge
ref      stable opaque URI owned by that service
sha256   optional source-object digest
```

The origin is stored in the immutable media-store revision and is projected by
`list` and `search`. It is deliberately metadata only:

- it never grants Telegram, tenant, object-store or originating-service access;
- it cannot select another destination or expand the current owner boundary;
- VibePublish does not dereference `origin.ref` or trust its payload as a command;
- changing the origin under the same request key is an idempotency conflict;
- provider bytes and their verified hashes remain independently authoritative.

This gives Regional Knowledge Base, Wonderful Lections and later services a
stable provenance hook without turning VibePublish into their document database.
The originating service owns document semantics, ACLs and lifecycle. VibePublish
owns only its media-store entry, provider identity, exact-byte evidence and the
temporary verified asset used for transfer.

## Cross-service asset provenance — 2026-10-02

Status: `Not confirmed by user` until merged/deployed and exercised through a real
consumer.

The media store may be used as a **secondary binary mirror** by another trusted
product such as Regional Knowledge Base or Wonderful Lections. It is not the
canonical owner of that product's document semantics or access policy.

`put` therefore accepts optional immutable origin metadata:

```text
origin.system     # e.g. regional_knowledge
origin.ref        # stable product URI, e.g. knowledge://illustrations/ill_...
origin.sha256     # consumer's canonical source/crop digest
```

The origin is stored inside the immutable media-store revision and returned by
`list` and `search`. It never grants access, changes Telegram routing, or
replaces VibePublish's independently verified provider-byte hashes. Reusing the
same request key with a different origin is an idempotency conflict.

This deliberately avoids a shared database between products. The consuming
service keeps its own ACL, page/caption/bbox/provenance graph and object-store
identity; VibePublish keeps the Telegram media identity and retrieval evidence.
If the canonical consumer object is deleted or its access is revoked, the
consumer must stop exposing the VibePublish reference even if the Telegram mirror
still exists.

## Availability boundary

No software can guarantee Telegram byte reads during a provider or
network outage. The product guarantee is therefore: local put admission and
text-only metadata reads remain available while SQLite/storage are healthy;
remote delivery is durable and eventually retried, never silently reported as
complete. Provider verification is reported only after exact native readback.

## Acceptance

- Unit/integration tests prove separation from connection quarantine, request-key
  idempotency, automatic transient retry, automatic known-ID reconciliation,
  local text-only list, verified-staging purge and exact provider byte retrieval.
- Production acceptance writes one real image document to topic 5, reads its
  caption from the local index, purges staging, then downloads the exact file from
  Telegram through the same exclusive VibePublish session.

## Local verification evidence

- Focused recovery regression: 40 passed plus 204 schema subtests.
- Contracts: 24 passed plus 200 schema subtests.
- Adapters: 81 passed; SDK: 22 passed; deployment: 26 passed.
- The active source contains the version-6 migration and version-1.6.2 skill.
- The updated 1.6.2 runtime source is active; server/worker are running with zero
  restart count, the worker holds the exclusive Telegram session lock, and owner
  tool projection exposes `vibepublish_media_store` with `put`, `list`, `search`
  and `get`.

## Crash recovery — 2026-09-19

The media index is part of the active VibePublish SQLite ledger, using
`publications` (`kind=media_store`), immutable recovery revisions, `facts` and
`fact_search`; `media_store_assets` tracks temporary staging/download bytes.
An empty `media_store_assets` table alone does not indicate a lost media bank.

The owner-designated topic `https://t.me/c/4379835477/5` was read using the shared
local Telegram E2E identity. Every image was downloaded, decoded and hashed; native
album membership and original captions were preserved. Transactional restoration
created 106 entries for the current owner identity. Replay added zero entries,
foreign-key/integrity checks passed, and no provider writes were dispatched.

Verified production reads: message 218 (one image), album 38–40 (three images),
including exact SHA-256 checks at the authenticated asset endpoint. Wonderful
Lections imported message 218 through its configured tenant-bound bridge into an
existing deployment-smoke presentation; readback matched the source hash.
Live `list` without `to` returned 50 indexed entries with `truncated=true`; a
subsequent verified provider thread read returned 20 items and did not erase any
of their hashes. Forty focused tests and 204 schema subtests passed.

[Incident and recovery record](../../reports/incidents/INC-2026-09-19-media-bank-recovery.md).
Retained evidence and source catalog:
`/home/dev/artifacts/vibepublish/20260919T074931Z-media-bank-recovery-20260919`.
These recovery copies are incident evidence, not a replacement for Telegram as
the product's durable media store.
