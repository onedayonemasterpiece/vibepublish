# MCP contract v1.1 — native queues and incremental receipts

Version: `1.1.0-design`. Owner corrections: `Fixed`. Engineering design: `Not confirmed by user`. Runtime: `Not done`.

Canonical schemas: [`contracts/social_mcp_v1.py`](../../../contracts/social_mcp_v1.py). Tasks: [`contracts/task_corpus_v1.py`](../../../contracts/task_corpus_v1.py). Runtime semantics: [implementation design](implementation-design-v1.md). Skill: [vibepublish-social-skill.md](../../llm/vibepublish-social-skill.md).

## 1. One task taxonomy

Eight methods remain: `get_started`, `publish`, `publication_update`, `visual`, `status`, `read`, `engage`, `destinations`, all prefixed `vibepublish_`. No new schedule/progress/history synonym tools. History and statistics are read queries; progress is an operation observation.

The original six/eight/split comparison remains a structural design choice, not an empirical weak-model A/B result. Active partner publishers now receive **six** core tools: bootstrap, publish, publication_update, visual, status and read. Read derives from active verified publishing bindings; it is not separately enabled by a legacy social.read scope. Without an active binding a partner has no social reads. Engagement and destination configuration require their corresponding rights. The owner may use all relevant tools within actual provider access.

`project_catalog(scopes, publish_destinations=..., owner=...)` consumes trusted server-auth context, not tool arguments. It removes owner-only dialog enumeration from partner read schemas. Exact item/destination authorization is still enforced in every handler; a hidden tool or schema-valid alias is not an access-control system.

## 2. Exact changed grammar

All object schemas remain closed and self-contained with reachable `$defs`. Native provider IDs, credentials and browser commands are not model-facing arguments. Use IDs/revisions/aliases/tokens returned by the server.

### Publish and lifecycle

```json
{
  "to": ["pka"],
  "content": {"text": "Открытие сезона — 6 сентября в 12:00."},
  "media": [{"source": {"kind": "asset", "id": "asset_1"}}],
  "delivery": {"kind": "at", "at": "2026-09-06T12:00:00+02:00"}
}
```

Scheduled delivery has exactly `kind` and `at`. `backend`, `late`, service fallback and local due-time execution are excluded, not merely deprecated defaults. `now` remains the default when delivery is omitted. `at` means submit to the real provider queue during this command and verify it there. Provider-specific minimum lead time and maximum horizon are semantic checks. Expired or too-close times are blocked, not converted to immediate sending.

`mode: preview` never submits to a provider. Approval/visual selection do not imply that a pending preview was already scheduled. Recheck timing and rights before its native submission. Default surface remains post; supported story/message/album/video/short_video map to actual capabilities. Native scheduling unavailable for a surface means explicit rejection/review, not local emulation.

`publication_update` still requires publication_id and expected_revision. Its change kinds are approve/edit/reschedule/cancel/delete/retry_failed. Reschedule modifies the existing provider queue item; cancel removes that item and verifies removal; delete acts on a published item. A never-dispatched intent can be cancelled locally, clearly distinguished from a native queue cancellation. No silent delete/re-create or automatic deletion after a cancel/publication race.

### Reads, queue, history and statistics

`vibepublish_read` supports item, dialogs (owner only), feed, stories, scheduled, notifications, audience, editorial_sample, thread, reactions, search, history and analytics.

`scheduled` always reads the provider's actual queue for the destination, not the local ledger. It includes entries created by other editors/clients where provider-visible. A provider error is not an empty queue. Each item can return publication_id/revision, queue_ref, observed scheduled time, actual URL or navigation hint, and protected preview_ref.

`history` searches the local publication-fact index. Fields: optional destination, author (mine/channel), text, from/to and state. Default author is mine; omitted destination means the current authorized destination set, not arbitrary channels. Channel mode returns known channel-visible facts, not other tenants' private drafts or operations. The index's coverage/freshness must not be represented as complete provider history.

`analytics` has one of two mutually exclusive target shapes: destination + from + to, or publication_ids. Freshness is cached (default) or refresh. Cached results disclose observation time and missing metrics. Refresh addresses stored provider identities and records progress and individual failures. Unknown metrics are not zero.

```json
{"query":{"kind":"history","author":"mine","text":"сезон"}}
```

```json
{"query":{"kind":"analytics","publication_ids":["pub_1","pub_2"],"freshness":"refresh"}}
```

The read response now uses the same durable receipt as other potentially long operations, with `items`, `truncated` and optional `next_cursor`. Fast local reads can return complete immediately; remote reads/refreshes can return accepted and then expose items through status. An accepted read with no items is not an empty final result. Every returned read item carries source, freshness and observed_at; statistics add metrics_observed_at and per-item error where necessary.

## 3. Progress: no wait-for-all barrier

Every accepted operation receipt requires:

- operation_id, action, state, message, operation_complete;
- per-destination deliveries with state, current stage and observed provider state;
- progress.events, progress.cursor and progress.has_more;
- next_action, retry_safe and receipt_ref.

The initial receipt is returned after durable local acceptance, before waiting on uploads or remote providers. Healthy-local-store acceptance target is two seconds, a release budget rather than a measured claim. Events are committed alongside state changes. Stage values include accepted, validating, importing_media, rendering, awaiting_approval/selection, waiting_connection, uploading, submitting, reading_back, verifying, finished, blocked and outcome_unknown.

Each event has an operation-local sequence number, operation ID, timestamp, stage, status and brief message, plus destination/media ordinal/evidence where applicable. Atomic means a committed meaningful transition, not every browser mouse movement. Do not fabricate percentage-complete estimates.

Example status request using a returned cursor:

```json
{
  "ids": ["op_1"],
  "after_event": "event_cursor_3",
  "wait_seconds": 10
}
```

It returns on the first new event from any child of op_1, an automatic-work termination/block, or the bounded timeout; it never waits for every provider. The response contains receipts with updated child snapshots and only the next event page. `wait_seconds` defaults to zero and is capped at ten. With after_event or wait_seconds, exactly one ID is required and it must resolve to one operation. The list-pagination cursor cannot be combined with an event cursor.

Event cursors are scoped to principal, policy epoch and operation, replayable after disconnect/restart. Use the returned cursor, not a guessed sequence. `has_more` means fetch remaining events without waiting. Cursor expiration or revocation returns a typed refresh/denial, never silently loses the gap or widens access. Snapshot state may be newer than the last returned event when paging; advance the cursor only over emitted events. Repeated event pages are deduplicated by operation ID and sequence.

Snapshots obtained without after_event give current states and a bounded recent-event window; detailed recovery uses the supplied durable cursor. `worker_seen_at`, last event time and explicit blocked/error state distinguish a waiting provider from a stopped worker. No new event means no invented progress.

MCP progress notifications mirror events only if the client supplied a valid active request token. They stop when that request ends, even if the durable job continues. Some clients may not display notifications or pass them to the agent; structured status is mandatory for all clients. In a polling client the agent reports useful partial outcomes to the user as they appear instead of staying silent until MAX finishes. Reconnection never invokes publish again.

All-target deterministic preflight still blocks unsafe mutations but emits its progress before all checks finish. After preflight, independent providers execute independently. A successful Telegram result is already in the receipt while VK uploads and MAX waits for its browser lane. A single MAX lock does not serialize the other providers.

## 4. Scheduling command completion and observations

`accepted` is not scheduled. `scheduled` means the requested items were read back in native provider queues. The scheduling command then returns operation_complete=true and next_action=none; it does not remain running until publication time. Per-delivery fields include scheduling_owner=provider, queue_ref/item_ref, actual scheduled time, evidence and preview/navigation information.

Actual later publication requires an observed published item or a proven provider identity mapping. The database keeps both queued and published identities. Queue disappearance, elapsed time or local uptime is not publication evidence. Provider-side video processing is represented separately as provider_processing.

Parent uncertainty cannot be hidden by partial success. Verified/scheduled children remain intact; an uncertain attempted child is never resent. `retry_failed` applies only to explicitly named, proven safe failures and rechecks native timing. Transport disconnect/cancellation stops the response wait, not accepted business work or a native scheduled post; use explicit domain cancellation.

## 5. Access and bootstrap

get_started returns scheduling=provider_native_only and read_policy of bound_publish_destinations, provider_visible_owner or none. It returns allowed aliases/sets and observed capabilities, configured timezone, server time, skill version/hash and policy epoch. Examples and approximate token counts remain versioned. Cache by principal + epoch + skill/schema version; current rights remain authoritative even with stale model context.

Partners may read every visible post, relevant comment thread and scheduled item in active publishing destinations, regardless of author. They cannot use a permalink, media reference, cross-post or query cursor to read another channel, the whole linked discussion chat or account-wide dialogs. The owner is not limited to publishing aliases for reads: provider-visible resource resolution can return owner-scoped handles without creating write grants.

Private source assets, prompts, candidates, credentials and operation histories remain private even if their resulting post is visible in a shared channel. Every cache/statistics/event/download path must enforce the same current destination/private-record boundary.

## 6. Unchanged content, visual and safety rules

Plain text by default; optional bounded Markdown or semantic paragraphs/links/mentions/emoji. Explicit provider renderings preserve differences. Ordered media come from owned refs, real HTTPS imports or host upload tickets; no invented paths or omitted attachments. Empty captions can be edited to empty, but runtime rejects an entirely empty resulting publication.

Visual generate/tune/compose use the same service for standalone/inline jobs; default two candidates and human selection. Exact typography uses copy fields; formats are post_4_5/story_9_16, tenant preset supplies branding. Selected output is first, explicit media follow; generation sources are not automatically attached. Selection binds the parent/revision/asset and cannot bypass approval or current native scheduling constraints. No model-visible training-consent flag.

Request replay/conflicting keys, immutable set snapshot, plan digest, external edits and unknown-outcome rules remain in the implementation design. Owner-only connection administration stays CLI initially. No raw SDK/provider command or generic options object is introduced.

## 7. Errors and HTTP projection

Before acceptance, return a closed error with code/message/field, next_action and retry_safe=false, without inventing an operation ID. After acceptance, errors/unknown outcomes remain on the durable receipt with progress. MCP transport errors and tool errors remain distinct.

Important repairs: invalid input/time -> fix_input; native scheduling unavailable -> contact_owner with the unsupported destination/capability; expired connection -> reauthorize; stale aliases/revisions/cursors -> refresh; access denied -> contact_owner; awaiting choice/approval -> select_visual/approve; automatic work running -> check_status; ambiguous provider effect -> review_outcome, never blind retry.

HTTP uses the same services: POST /v1/publications, /v1/publications/{id}/commands, /v1/visuals/commands, /v1/engagement/commands, /v1/destinations/commands, /v1/reads; GET /v1/operations/{id} and /v1/bootstrap. Operation GET supports the same after_event/bounded-wait semantics. HTTP 202 is only durable acceptance. Mutation clients supply Idempotency-Key. Optional application event streaming is a projection of the same authorized journal, not a second state mechanism.

## 8. Executed design checks and unexecuted runtime gates

Command run locally on 2026-09-04 with jsonschema 4.26.0:

```bash
python tests/contracts/test_social_mcp_design.py
```

Result: **14 test methods passed**, **16 input/output schemas**, **105 golden calls**, **30 negative calls**. Added checks cover rejected backend/local-late fields; required progress receipts; mixed Telegram-complete/VK-uploading/MAX-waiting snapshots; scheduled-command completion distinct from publication; event cursor argument boundaries; inherited partner read projection and hidden owner dialog enumeration; history and exact-item statistics grammar.

These tests validate schema/projection design and corpus coverage. Runtime-oracle labels for permissions, event timing, provider behavior and crash recovery are requirements, not simulated passes. No live weak model, database concurrency test, MCP-client notification test, provider/native-queue canary or MAX browser run occurred here. The input schemas and corpus can be rendered with their Python entrypoints; generated JSON is not another source of truth.

Required integration tests additionally prove: prompt acceptance during a stalled provider; first-child events while others run; no progress-token use after response; operation replay after disconnect; full queue reads of other editors' posts inside the allowed channel; denial outside it including cache; and provider execution after all VibePublish processes are stopped. Real weak-agent comparison remains required before releasing the server; no model accuracy percentage is claimed.

Official progress semantics checked: https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress . Provider-native queue reference: https://core.telegram.org/api/scheduled-messages .
