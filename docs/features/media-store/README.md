# Private media store

Status: `Not confirmed by user` — requirements and implementation are complete;
local checks pass and production exposes contract 1.6.0 after the version-6
migration. The first user-visible Telegram media-database write remains to be
confirmed in the target topic.

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
- `list` is text-only and scoped to one explicitly named Telegram topic.
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

- Runtime: 179 passed (including eight media-database lifecycle tests).
- Contracts: 24 passed plus 200 schema subtests.
- Adapters: 81 passed; SDK: 22 passed; deployment: 26 passed.
- The built wheel contains the version-6 migration and version-1.6.0 skill.
- Production release `1a944d3c639850dc8977ae216f15993313076ae5` is active;
  server/worker are running with zero restart count, the worker holds the exclusive
  Telegram session lock, and owner tool projection exposes
  `vibepublish_media_store` with `put`, `list`, `search` and `get`.
