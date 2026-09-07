# MCP contract v1.5 — native queues, incremental receipts and visual choice

> Current remote delivery: **partial, not a runnable release**. The implemented
> behavior and historical test counts below describe the complete archived source.
> Three production modules remain undelivered; current evidence and exact boundaries
> are in [runtime status](../../operations/social-runtime.md).

Version: `1.5.0-runtime` (base design `1.1.0-design`). Owner corrections: `Fixed`. Offline implementation: `Not confirmed by user`; retained/live gates: `Not done`.

Canonical schemas: [`contracts/social_mcp_v1.py`](../../../contracts/social_mcp_v1.py). Tasks: [`contracts/task_corpus_v1.py`](../../../contracts/task_corpus_v1.py). Runtime semantics: [implementation design](implementation-design-v1.md). Skill: [vibepublish-social-skill.md](../../llm/vibepublish-social-skill.md).

## 1. One task taxonomy

Eight methods remain: `get_started`, `publish`, `publication_update`, `visual`, `status`, `read`, `engage`, `destinations`, all prefixed `vibepublish_`. No new schedule/progress/history synonym tools. History and statistics are read queries; progress is an operation observation.

The original six/eight/split comparison remains a structural design choice, not an empirical weak-model A/B result. The default full publishing policy projects **six** core tools: bootstrap, publish, publication_update, visual, status and read. Read derives from active verified publishing bindings; it is not separately enabled by a legacy social.read scope. Without an active binding a partner has no social reads. Narrower policy can remove visual and its inline branch. Engagement and destination configuration require their corresponding rights. The owner may use all relevant tools within actual provider access.

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

`publication_update` still requires publication_id and expected_revision. Its change kinds are approve/edit/reschedule/cancel/delete/retry_failed/reconcile. Reschedule modifies the existing provider queue item; cancel removes that item and verifies removal; delete acts on a published item. A never-dispatched intent can be cancelled locally, clearly distinguished from a native queue cancellation. No silent delete/re-create or automatic deletion after a cancel/publication race.

### Original-terminal recovery (owner MAX completion correction, 2026-09-08)

Requirements: **Fixed** by the active owner MAX completion task in PR #2,
`docs/handoffs/max-product-completion-codex-20260908.md`. Implementation:
**Not confirmed by user**; automated checks are not live MAX acceptance.

```json
{
  "publication_id": "pub_original",
  "expected_revision": 1,
  "change": {
    "kind": "reconcile",
    "operation_id": "op_original",
    "attempt_id": "attempt_original",
    "native_reference": "https://max.ru/exact-task-owned-reference"
  },
  "request_key": "observe-original-once"
}
```

`reconcile` is an additive branch of `publication_update`, not a retry/send tool.
It returns the **original** operation and revision. No new operation, attempt,
publication, frozen plan, or dispatch marker is created. `operation_id` must be
an exact private operation belonging to the supplied publication and its current
revision; `item_ref` adoption is forbidden. The optional exact reference requires
an explicit original attempt (private receipt deliveries now expose `attempt_id`). It is untrusted evidence input, not permission to
navigate arbitrary targets, nor proof of a publication by itself.

Admission rechecks the authenticated principal, `publication.manage` tool scope,
original actor epoch, all original binding epochs, current binding access and
mutation rights. Worker observation and resolution recheck active authority,
connection/target/secret-reference identity, the original plan digest and the
worker fence. A revoked original epoch requires an explicit owner remediation;
it is never rewritten to the new epoch. Native-reference hints are durably tied
to the original attempt/plan/checkpoint; an already admitted different reference
is rejected. Repeated request keys join running work or replay a resolved receipt. After a
transient observation ends unknown, the same matching key may re-admit observation
of the original attempt; no new key or effect is needed. A running operation
is joined rather than concurrently reopened. Successful siblings remain untouched.

Only originally dispatched `outcome_unknown` children are reopened. The worker
uses **reconcile only**, never prepare/execute/before_effect for these children.
The old send deadline does not prohibit read-only recovery. Provider reconciliation
receives the original checkpoint plus top-level `core_recovery` containing
`operation_id`, `attempt_id`, `plan_digest`, and optional `native_reference`.
Providers independently check original durable intent and native attribution;
MAX must verify its original marker and fresh exact native item. A positive exact
identity need not prove completeness of unrelated history. Missing checks,
wrong content/target/media/time/identity, or an unknown observation remain unknown;
core does not convert an uncertainty enum into a success.

SQLite schema 4 adds `attempt_recovery`: immutable original checkpoint and plan
identity, admitted hints, full native observation, resolution and finalization
state/timestamps. Exact observation, child receipt and history fact, and any
pending finalization are committed atomically. The resolved child checkpoint
contains `remote`, `original_checkpoint`, and `core_recovery`; historical evidence
is preserved instead of overwritten by a bare success snapshot. Recovery metadata
is private; raw hints/checkpoints are not added to public receipts.

Providers may implement the additive optional
`finalize(request, checkpoint, hooks) -> None` hook. It runs only **after** durable
child resolution and receives that resolved checkpoint envelope. It must release
only quarantine matching the original attempt/digest; absent quarantine is
idempotent success, different quarantine is an error. It must never perform a
social effect. Old Telegram/VK/provider implementations without the hook remain
compatible. A pending hook does not relabel a verified child as unknown, but keeps
the operation incomplete and blocks new effects on its connection. The worker
retries finalization after a 30-second lease interval or process restart. A crash
before release or after release but before acknowledgement replays only this
idempotent hook, never execute or an already successful child's readback. Successful
resolution removes stale uncertainty errors from the original receipt.

Offline regression lives in `tests/runtime/test_recovery.py`; the transport suite
also exercises authenticated MCP `ClientSession` admission, disconnect/reconnect,
and independent worker processes against the durable provider simulator. These
prove core wiring/no duplicate effect in the simulator, **not** MAX live behavior.
The independent CI `core-recovery` job runs runtime/contract/provider/SDK tests on
Python 3.12 and 3.13, uploads JUnit/SDK/source-SHA receipts, and stays runnable when
an unrelated full-suite collection problem exists. The original strict `verify`
matrix is unchanged and remains mandatory: a green focused job must not be reported
as green full CI. The pre-existing missing `adapters.codex_imagegen` is reported
separately, never hidden or skipped in that strict gate.

### Explicit safe retry before dispatch

`publication_update` also implements its existing `retry_failed` branch:

```json
{
  "publication_id": "pub_original",
  "expected_revision": 2,
  "change": {"kind": "retry_failed", "destinations": ["max"]},
  "request_key": "retry-blocked-edit"
}
```

This explicitly re-admits the **same operation, revision and selected attempts**
only when they are completed blocked/failed attempts with `dispatched=0`. It is
not a new publication or revision and does not depend on a successful checkpoint:
the original immutable plan already contains the existing native item/CAS for an
edit, reschedule, cancel or delete. Current actor/binding epochs and rights,
connection/target identity, frozen emoji access and asset integrity are rechecked.
Successful siblings and their receipts remain untouched. Unknown outcomes anywhere
in the operation, or any selected previously dispatched child, reject retry;
uncertain effects must use observation-only reconciliation instead.

Authorized retry renews only the 120-second immediate command deadline, then uses
the normal prepare → before_effect dispatch CAS → execute path. Original content,
assets, native identity and requested schedule remain frozen. Provider preflight
must still prove the native object unchanged; an expired native time blocks rather
than falling back to immediate publication. Exactly one dispatch transition is
possible for the selected original attempt, including across retries and restarts.

The same matching request key joins in-flight work or replays successful results.
If another attempt stops before dispatch, that same key may explicitly re-admit
it again. A retry that crosses dispatch and becomes unknown cannot be submitted
again. Durable events distinguish retry admission from the preceding failure.
The original failed operation's publication revision remains usable for later
lifecycle changes after successful retry; private item adoption is not required.
Tests include authenticated MCP ClientSession and independent worker processes,
expired command/native deadlines, external changes, epochs and partial successes.
Implementation status: **Not confirmed by user**; offline checks are not live MAX
acceptance.

### Opt-in native MAX worker wiring

The ordinary owner CLI accepts `connection --provider max --account-type max_web
--secret-ref VIBEPUBLISH_MAX_PROFILE`. `worker --native` selects this exact active
connection family; `serve`/MCP admission never launches a browser. Fake or
unconfigured connections are still skipped. Wrong MAX account types or secret
references fail closed before importing or opening any MAX session.

`adapters.wiring.native_adapters(..., max_factory=None)` lazily imports the optional
`adapters.max.live_session.configured_adapter` only when a configured MAX connection
is selected. A missing optional MAX package returns `max_adapter_not_installed`.
Telegram/VK need no MAX installation when MAX is not selected; their credential
validation, retry disabling and cleanup remain unchanged.

The callable contract is an async context manager:
`configured_adapter(*, connection_id: str, env: Mapping[str, str])`, yielding the
actual provider adapter. Its context owns profile/browser startup and cleanup;
core's `AsyncExitStack` closes entered contexts on completion, errors or cancellation.
The MAX package validates explicit `VIBEPUBLISH_MAX_PROFILE` configuration and
requires approved profile/executable/allowlist and write opt-in; core does not
parse or guess MAX profile paths, copy sessions, or borrow credentials. The same
callable can be injected through `max_factory` for offline tests. There is no
custom provider worker or alternate social dispatch path.

Implementation status: **Not confirmed by user**. The core seam has offline
factory-lifetime and standard CLI worker tests; MAX configuration, actual browser
capability and live acceptance remain in PR #2. The focused core CI includes these
tests, while the strict full-suite gate remains separate and unchanged.

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

These tests validate schema/projection design and corpus coverage. Runtime-oracle labels for permissions, event timing, provider behavior and crash recovery are requirements, not simulated passes. The historical design-only validation did not execute runtime tests. The current runtime runbook separately records actual database/process and MCP ClientSession tests. Live weak-model comparisons, provider/native-queue canaries and MAX browser runs remain unverified. The input schemas and corpus can be rendered with their Python entrypoints; generated JSON is not another source of truth.

Required integration tests additionally prove: prompt acceptance during a stalled provider; first-child events while others run; no progress-token use after response; operation replay after disconnect; full queue reads of other editors' posts inside the allowed channel; denial outside it including cache; and provider execution after all VibePublish processes are stopped. Real weak-agent comparison remains required before releasing the server; no model accuracy percentage is claimed.

Official progress semantics checked: https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress . Provider-native queue reference: https://core.telegram.org/api/scheduled-messages .

## Runtime extension 1.3: existing native items

`publication_update` selects exactly one identity: `publication_id` with
`expected_revision`, or `item_ref` from an authorized provider read. The read ref
binds native target, namespace, content/media fingerprint and principal epoch.
It is the CAS for an externally created item. No synthetic provider revision is
required and no other author's private publication is exposed. HTTP equivalent:
POST `/v1/items/{item_ref}/commands`; the canonical tool count remains eight.


## Runtime extension 1.4: shared visual jobs and private assets

The eight names are unchanged. Standalone visual generate/tune/compose and inline
publish.visual enter one VisualService. Admission freezes parent plans, budget,
sources, policy/routing revision and requested route. No parent provider attempt
exists until an eligible candidate is selected. Job IDs work in status as well as
operation IDs. Receipts include visual_job_id, visual_revision, candidates with
format/selection_token/requires_review, separate requested/actual executor data,
and selected_asset_ref/selected_sha256 after selection.

Select is a job-revision/candidate-token CAS. It resumes the original operation
once with a new immutable publication revision and selected media first. Preview
mode is preserved. Changed rights, editorial revision, routing or native schedule
window blocks continuation. Other candidates, sources and private operations are
not exposed across principals. Feedback is append-only and not shared training.

Authorized GET /v1/assets/{id} and MCP resource template
vibepublish://assets/{asset_id} return verified private bytes; no-store and current
scope/origin checks apply. These are resources, not extra mutation tools. Direct
inline visual arguments are denied when visual scope is absent, not merely hidden
from list_tools. The initial real-preset automatic-choice and live executor gates
are explicit in the canonical visuals document.


## 1.5 runtime delta: Telegram palettes and semantic entities

Three new closed `destinations.command` alternatives: `emoji_set_register`,
`emoji_alias_select`, `emoji_rule_put`. Two `read.query` alternatives:
`emoji_catalog` and `emoji_palette`. `get_started.section` accepts `emoji`.
All are removed from scoped catalogs without publishing permission. Eight tools
remain eight. The [emoji workflow](telegram-custom-emoji-v1.md) contains the
implemented flow, bounds and explicit live/SDK/animation gates.

Publish/edit may carry `emoji_context` and `emoji_fallback: approved_text`.
No raw native entities are accepted from callers. Read/preview receipts expose
closed semantic entity records including decimal-string custom document IDs.
Read-only content evidence is not a provider invocation API. Render-only missing
fallback gates can block an execute child independently, while the original
all-target preflight rule remains for rights, CAS, deadlines and unsafe effects.
