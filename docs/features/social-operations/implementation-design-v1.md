# VibePublish — implementation design v1.1

Date: 2026-09-04. Correction base: `f285dace053f91e322b7015e28e38c14d405b3b9`.
Owner corrections in [README](README.md): `Fixed`. Engineering details: selected for implementation, `Not confirmed by user`. Runtime: `Not done`.

This revision replaces the earlier local-scheduler architecture and separate partner read-grant requirement. Historical audit/handoff text is not authoritative for those decisions. No Codex, provider mutation or deployment was run for this correction.

## 1. Requirement delta and product boundary

| Classification | Result |
|---|---|
| Already present | Independent service; Telegram/VK/MAX Web; own/shared credentials; exact aliases; imagegen; immutable plans; per-target receipts; no blind retries; media integrity |
| Rejected and replaced | Service scheduling default/fallback -> native provider queues only; separate partner read grant -> full reads inside active publishing destinations; waiting for aggregate results -> incremental per-stage receipts |
| Added | Indexed publication facts/statistics; actual provider queue previews; durable progress replay; queue-to-published identity mapping; native-queue offline-execution canary |

VibePublish accepts an editorial intent, executes a provider command now, records what happened and exposes facts. A scheduled publication is an instruction sent now to a provider that will perform the future publication. The system does not own that future execution.

The first slice must cover native scheduled and immediate posts/media, full reads of partner-bound channels including their queues, lifecycle changes, progressive receipts and indexed history. Full donor-compatible stories, rich media, reads, engagement and analytics remain required when connection/surface capabilities support them. Unsupported native scheduling of a particular surface is explicit; a local timer is never the substitute.

## 2. Architecture: command executor and ledger, not a calendar

```text
MCP / HTTP / EventsBot / editorial UI
                  |
      API + authorization + prompt receipt
                  |
      SQLite ledger / facts / progress events
                  |
           command executor NOW
         /          |          \
    Telegram       VK       MAX Web
         |          |          |
    native queues owned and executed by providers
```

One Python application, API process and command-worker process; Python 3.12 with exact SDK/browser versions locked at implementation. SQLite/WAL on local persistent storage, foreign keys, short transactions and busy timeout. No network-mounted SQLite, additional broker, Redis or new PostgreSQL service without demonstrated need. Optional existing Supabase Google quota accounting is not the social ledger.

The worker executes imports, generation, uploads, immediate sends, native queue submissions, edits and bounded observations. It may have a durable ready-command backlog and short operation-bound rate-limit backoff. **There is no publication due-time queue, `send_at` timer, periodic due-post scan, cron sender or local scheduled-delivery fallback.** Requested publication time belongs to the immutable provider command/fact, not task eligibility.

Commands have bounded processing deadlines derived from deployment budgets and native submission constraints; they cannot remain pending until the future publication time. Restart may resume an unattempted command only while that deadline and its authorization remain valid. A command already submitted remotely is reconciled, not re-created. Failed submission becomes failed/blocked/unknown, never a promise of later local publication.

Planned ownership:

| Module | Responsibility |
|---|---|
| `social_operations/domain/` | Entities, revisions, digests, state invariants |
| `social_operations/services/` | Auth, publish/update, bounded reads, history/statistics, visuals |
| `social_operations/storage/` | SQLite repositories, ready-command outbox, events and indexed facts |
| `adapters/telegram/`, `adapters/vk/`, `adapters/max/` | Provider capabilities, exact native command and observation |
| `adapters/imagegen/` | Bounded executor/artifact contract, no social credentials |
| `mcp/`, `api/` | Exact schema projections and auth adapters over the same services |
| `worker/` | Immediate command claims, short retries, recovery and observations; no publication scheduler |

Provider observations arrive through supported updates/webhooks or explicit queue/item/statistics reads. A due timestamp alone never marks a post published and never triggers a local send. No mandatory periodic reconciliation scheduler is introduced by this design.

## 3. Persistent data and atomicity

| Entity | Required fields and boundaries |
|---|---|
| tenant/principal/credential | Status, hashed revocable service credentials, policy epoch; provider secrets are separate encrypted records |
| connection | Provider account identity, secret/profile reference, authorization epoch, rights observation, connection-wide cooldown |
| destination/binding | Immutable native target, tenant alias, authorized publishing principals and operation rights; exact connection mapping |
| destination_set | Unique tenant alias, revision and concrete member IDs; no nested sets |
| publication/revision | Initiator, request identity, semantic and provider-rendered content, frozen destinations/media/visual, requested provider time, immutable plan digest |
| delivery | Destination, provider surface, latest observed state/revision, opaque scheduled and published item bindings, current attempt |
| operation/attempt | Command, actor, CAS revision, dispatch boundary, stable provider request identity, deadline, lease and fence; no future send trigger |
| ready_command | Operation reference, processing lease/fence, bounded retry metadata; never a publication calendar |
| operation_event | `(operation_id, seq)` unique; destination optional; timestamp, stage, status, message, media ordinal/count, protected evidence reference |
| publication_fact | Stable service publication ID; destination, provenance/initiator, origin, content/media fingerprints, remote IDs, observed timestamps/state and searchable excerpt |
| statistic_observation | Publication/destination, metric name/unit/value, provider observation time, scope/availability and provenance |
| asset/derivative | Tenant ownership, immutable bytes/hash, geometry/duration/MIME, provenance, rights and retention |
| visual/candidate/decision | Job identity, sources/outputs, preset, exact selected hash, feedback and separate training permission |
| approval/quota/evidence | Scoped single-use approval, conservative cost reservation, protected readback evidence |

Private resources use tenant-aware foreign keys and mandatory authenticated repository context. Public-to-an-authorized-channel content is a separate projection; do not copy another tenant's private operation record into it.

Acceptance transaction: authenticate and validate bounded input, resolve local bindings, freeze aliases/set membership, reserve request identity, persist the operation and an `accepted` event plus ready command. Do not block the initial response on external fetches, uploads, generation or provider rights calls. Necessary remote preflight then runs visibly before any provider mutation. Unknown aliases or invalid local authorization fail before acceptance, without invented operation IDs.

Claim transaction: CAS claim, increment fence, recheck current rights before dispatch. Commit `dispatch_started` before the side effect. A lease/fence prevents stale local writes, not a remote API/browser action; an expired lease cannot authorize a second send after this boundary.

Each transition transaction writes state and its event together, with a strictly increasing sequence within that operation. A completion stores facts/evidence and event atomically. There is no transaction held across external I/O and no event published before commit. Per-provider results persist immediately, not at a fan-out barrier.

## 4. Native scheduling and real preview

Input `delivery` is either `{kind: now}` or `{kind: at, at: RFC3339-with-offset}`. There is no backend selector or local late-send policy. The service normalizes time in the configured tenant IANA zone, shows original/effective time and rejects ambiguous/nonexistent local time, past time and unsupported provider horizons.

For scheduled work, perform the native queue submission during the command. Require an actual remote queue/item identity, observed scheduled time, rendered text/links, media count/order and supported asset-binding evidence. Only then report `observed: provider_scheduled`. The scheduling command is now complete and the provider can execute independently of VibePublish.

The provider preview is the actual queued item, not merely our simulated layout. Return an actual provider URL if supported, otherwise exact authorized navigation instructions plus a protected preview/evidence reference. No invented deep links. A partner without direct upstream login still sees the authorized queue representation through VibePublish; the server cannot grant a provider's UI login by returning a link.

Capability checks are per connection/destination/surface: native creation, queue listing, exact queue item read, time/content edit, cancellation and identity reconciliation. These are required implementation goals, not an assertion that every MAX Web surface is already supported. If missing, return `native_schedule_unsupported`, `needs_auth` or `needs_review`. Deterministic all-target preflight blocks a mixed request with known unsupported targets before any submission; the user may then select supported destinations explicitly.

Near-time danger: some provider APIs can send immediately when the chosen time is too close. Enforce a provider-specific minimum lead time plus submission/clock-skew safety margin immediately before the guarded call. Telegram's documented behavior includes immediate delivery for schedule dates less than ten seconds ahead; do not treat any future timestamp as safe. If generation, approval, queue contention or network preparation closes the safe window, block with a new-time action. Do not round into immediate delivery or silently postpone. Ambiguity after the actual call remains unknown and is observed.

A preview-only request or a request awaiting visual choice has not yet entered the provider queue. A selected/approved final plan must still pass the native lead-time and rights checks. `accepted` never means scheduled.

## 5. Cancellation, rescheduling and external changes

`publication_update` acts on the exact current publication revision and its bound provider items. Read live provider state before editing; compare it with stored fingerprints. Manual provider-client edits produce an updated observation and a revision conflict, not automatic overwrite. Where the provider has no atomic CAS, local conflict checking is explicitly best effort, followed by readback.

`reschedule` changes the existing scheduled item's time at the provider. `cancel` removes an existing native scheduled item and verifies the outcome there; for a never-dispatched intent only, cancelling locally is sufficient and is labelled as such. `delete` removes an already published item. These commands are not interchangeable.

No silent delete-and-recreate rescheduling. A driver without in-place support returns an unsupported/review result; a future explicit replacement workflow would require separate authorization and proof against duplicates. Queue discovery may create a local fact/reference for a post authored outside VibePublish; its `publication_id`/revision is returned so the same lifecycle tool can manage it if the actor has the necessary mutation rights.

A cancel/send race may find that the item has already published. Report that observation; do not label it cancelled or automatically delete it. Queue absence alone proves neither cancellation nor publication. Native deletion evidence, provider identity mapping or exact post readback must establish the result; otherwise keep unknown. Albums/multi-item outputs retain individual remote identities and partial changes.

Revocation blocks new local actions and pending unsubmitted commands and invalidates cached channel access. It does **not** retroactively erase accepted native schedules. Revocation and remote cancellation are separate authorized actions. Owner administration must show which provider-queued items may remain and offer exact explicit cancellation while access exists; no hidden cleanup authority is inferred from revocation. In-flight outcomes are observed under internal audit authority without leaking content to a revoked partner. If provider access disappeared, residual remote work is reported honestly.

## 6. Incremental operation visibility

Portable behavior is mandatory, independent of UI support for MCP notifications:

1. Return a durable initial receipt promptly, with `operation_id`, `operation_complete: false`, known child states, initial events and an event cursor. Implementation target: within two seconds under a healthy local store; do not wait for external providers. This is an acceptance budget, not a measured performance claim. Local admission failure returns an error rather than fake acceptance.
2. Record and expose atomic stages per provider as they commit: validation, asset import/rendering, waiting for connection lane, uploading each media item, submitting, reading back, verifying and completion/block/unknown.
3. `status` with one operation ID, `after_event` and bounded `wait_seconds` returns on the **first** available event from any child, completion/blocked transition, or a maximum ten-second wait. It does not wait for all providers or for a page to fill. Return the latest per-target snapshot plus ordered event deltas.
4. Reconnect/restart reuses the durable cursor. A cursor is opaque and bound to principal, policy epoch and operation. Advance only to the last emitted event; expose `has_more` when bounded output leaves events unread. At-least-once replay is deduplicated by `(operation_id, seq)`, never by repeating provider work.

No preflight or upload `gather` may hold events until all awaited calls finish. All-target preflight remains a **mutation safety** barrier, not a reporting barrier. After it passes, connections proceed independently. A MAX profile serializes its own interactions, not Telegram/VK responses. Event sequence reflects committed observations, not a fictional cross-provider execution order.

When there is no new event, return the last real stage/time; do not invent percentages or progress. Worker heartbeat and operation deadline diagnostics must distinguish waiting for the connection, waiting for the provider and a stalled worker. A stalled command has a visible error/blocked state; it is not silently represented as ordinary progress forever.

MCP `notifications/progress` may mirror events when a client supplies an active request progress token. They stop when that tool call completes; the server must not continue using a completed request token for a durable job. Notifications do not guarantee that an LLM sees intermediate state. Structured status calls are the required fallback, including during clients without notifications. An optional application HTTP event stream can replay the same authorized event log; it is not required to complete the MCP workflow.

Long provider reads/statistics refreshes use the same early receipt/event mechanism, with returned items attached to the read operation's receipt. Local history/status/bootstrap reads are bounded and need not wait on a remote provider. No new progress tool, provider-specific status tool or client prepare/commit sequence is added.

Cancellation of a transport wait stops that wait, not an already accepted business operation or native scheduled post. Explicit domain cancellation uses `publication_update`. Protocol-version behavior must be verified against the actual SDK and client, not guessed.

## 7. States, partial delivery and idempotency

Separate desired intent, operation phase and observed provider state. Public states are `accepted`, `running`, `needs_approval`, `needs_selection`, `scheduled`, `verified`, `partial`, `failed`, `outcome_unknown`, `cancelled`, `blocked`. There is no `service_queued` provider observation.

`operation_complete` means the command's automatic work has ended, not that a future scheduled post has already published. All destinations confirmed in native queues -> `scheduled`, complete, next action none. Later actual publication is a new observation of the publication fact, not a reason to reopen the original scheduling command. Provider-side video processing is distinct from time scheduling.

During fan-out retain each child's state/stage. Any uncertain attempted child makes aggregate uncertainty visible; otherwise unfinished work remains running; ended mixed success/failure is partial. A success on one provider is never erased by another's failure. No automatic rollback across providers and no retry of verified/unknown children.

Keep two digests: request digest over stable caller intent/principal and normalized arguments; plan digest over exact targets/bindings, renderings, ordered hashes, surface, native time and selected visual/preset revision. Selection cannot retroactively alter request identity. Freeze concrete set members; later changes cannot redirect existing work.

Deterministic HTTP callers supply an idempotency key. MCP optional keys retain the 24-hour principal-scoped normalized-intent duplicate guard. Exact replay returns the original receipt before URL fetching/set resolution; conflicting key reuse is rejected. Explicit repeats require user authority, a fresh key and `repeat_of`. Preserve key tombstones for at least 90 days and longer for native queued/unknown operations. Idempotency history does not turn the DB into a scheduler.

Persist the side-effect boundary before provider I/O. Crash/timeouts after it are possibly applied even with no saved response. Provider-specific stable request IDs are reused only when proven safe. An identical old post or missing search result cannot resolve uncertainty. A retry is allowed only for a child proven not applied and within native timing/rights constraints.

Source SHA-256 proves input bytes, not equality after recompression/transcoding. Readback separates source digest, provider object identity, rendered content/links, count/order and semantic media properties. Incomplete verification is explicit, never a fabricated remote hash or a reason to repost.

## 8. MAX Web native queue driver

MAX remains a dedicated Playwright adapter. No API approval prerequisite and no MAX API implementation in this release. One persistent profile belongs to a provider connection; encrypted-at-rest dedicated storage, restricted OS user and permissions, one profile lock and one serial side-effect lane. Shared operator connections expose only the authorized destination projection, never cookies, unrelated dialogs or full DOM.

```text
CHECK_SESSION -> OPEN_EXACT_TARGET -> VERIFY_ACCOUNT_AND_TARGET
-> COMPOSE -> FILL_TEXT -> UPLOAD_ORDERED_MEDIA
-> SET_NATIVE_TIME (scheduled commands only)
-> VERIFY_COMPOSER_AND_TIME -> DURABLE_DISPATCH_STARTED
-> SUBMIT_ONCE -> OPEN_NATIVE_QUEUE / OPEN_FEED
-> LOCATE_EXACT_ITEM -> VERIFY_CONTENT_MEDIA_TIME -> EVENT + RECEIPT
```

Scheduled readback opens the actual provider queue. Edit/reschedule/cancel open the exact queued item; ordinary publication readback opens the feed. Verify account, immutable target identity and unique item binding, not display name alone. Prefer scoped role/label locators and re-acquire after DOM changes. Never use unchecked nth-match/coordinates as primary identity selection.

Before dispatch deterministic recovery may reopen/reconstruct the composer from the immutable plan. After dispatch, recovery is observation-only until the outcome is resolved. Handle virtualized lists, duplicate-looking posts, target renames, delayed uploads, timezone ambiguity and session expiry. If no stable remote ID is exposed, retain a protected exact locator/evidence binding; nonunique candidates remain unknown.

Proposed bounded execution: up to two pre-submit recoveries within a 90-second MAX attempt budget; no recovery may cross the native minimum-lead window. Bounded follow-up observation does not schedule a future send. QR/OTP/CAPTCHA, changed identity, lost rights and exhausted budgets require a visible action, not autonomous authentication bypass.

Model-assisted locator recovery is deferred and optional: at most one sanitized nonmutating proposal for an unknown pre-submit transition, under an explicit data policy. It cannot publish/delete, select a different target, change payload/time, inspect secrets, execute arbitrary JavaScript or resolve an ambiguous submit by repeating it.

Offline fixtures test state transitions only. The live gate includes real native queue creation/read/preview/reschedule/cancel and a canary where the VibePublish API/worker/browser are stopped after confirmed scheduling and the provider later executes. If MAX Web cannot support that native capability, report the gap without building a local workaround.

## 9. Read authorization and searchable history

Effective publication authority is active principal + exact binding + allowed action + active connection + actual provider rights + approval policy. The **same active publishing destination boundary implies social-read access** for partners; it does not require a separate read grant. Own and operator-shared connections follow the same destination rule.

A partner may read the entire permitted channel, its native queue, its posts from other editors and authorized post threads/media/statistics. No creator filter is applied to provider queue/feed reads. Searches are constrained to those destinations before any external request; unauthorized exact refs, renamed aliases or links fail with a nonenumerating access denial. Account-wide dialogs/search/notifications/analytics cannot leak into partner responses. Resource-bound notifications/statistics are allowed only when the adapter can constrain them safely.

The owner can resolve/read anything actually visible to the provider account without registering it for publication first. Owner resolution may produce an owner-scoped ephemeral handle; resolving a handle does not create a partner binding or a write grant. Unavailable private chats remain unavailable.

Channel-visible objects are not the same as tenant-private objects: a partner may see a scheduled image another editor attached to that channel, but cannot use its identity to retrieve the editor's original draft, prompts, feedback, other assets or operation history. Use authorized provider/media projections or explicit channel-visible asset bindings, not guessed global SHA access. Private status/visual/approval records stay principal/tenant scoped.

History design:

- Index by authenticated initiator, destination and observed time; FTS over normalized searchable text, filtered by current authorized destinations before counting/pagination. No external feed scan for ordinary history lookup.
- `history` defaults to `author: mine` within the current allowed destination set. `author: channel` exposes known channel-visible facts, not other tenants' private records. Return origin and observed freshness; the local index is not a claim of complete provider history.
- Use exact stored remote identities for statistics. Cached statistics return observation time and unavailable metrics explicitly; unknown is not zero. Refresh fetches only requested items, persists observations and exposes per-item progress/errors. Preserve provider-specific metric semantics instead of summing incompatible counts.
- Native scheduled reads always contact the provider. A provider error is not an empty queue; local records may be shown only as labelled historical evidence. Snapshot pagination must not mark items missing until the relevant provider scope was successfully enumerated.
- Keep scheduled-ID and published-ID namespaces separate under one stable service publication ID. Use provider update mappings when available; otherwise exact bounded readback. Time passing or queue disappearance alone never proves publication. Telegram explicitly distinguishes queued and sent message identities.
- Manual provider edits/reschedules/cancellations are recorded as external observations, not overwritten by the local desired plan. Discovery returns a safe publication reference/revision for subsequent authorized edits.

Revocation invalidates bootstrap, event cursors, history filters and asset URLs. Recheck before serving cached content and before every next page/wait response, not just when issuing a cursor. Sharing one physical operator connection never permits cross-destination cache leakage.

## 10. Assets, security, quotas and operations

Secure onboarding separates service tokens from provider secrets. Owner-created short-lived setup links/CLI secret input provision tenant connections; no credentials in model arguments, source files, URLs, prompts or ordinary logs. Use proven auth implementations, validate issuer/audience/expiry/scopes, and never pass the caller's service token to a provider. MAX login is supervised by the authorized human.

Media ingress supports owned refs, constrained HTTPS downloads and real host upload tickets. A ChatGPT local path is not a server file. Block private/loopback/link-local/metadata networks, revalidate redirects/DNS, limit bytes/decoded pixels/duration and time, sniff/decode MIME in constrained processes, sanitize names and prohibit active raw SVG. Authenticated provider downloads use separate allowlisted adapter paths. Preserve original assets privately; do not publish EXIF location by default.

Source content, comments, filenames, metadata and DOM are untrusted data. They cannot request new actions, expand access, select a target or authorize publishing. Test injection and cross-tenant guessed-ID/cache attacks. Tenant training use is separately consented; imagegen receives only its source manifest and constrained workspace, never social credentials.

Quota reservations cover tenant/principal commands, candidates, storage/bandwidth, concurrency and shared provider limits. Reserve before costly work, settle actuals, keep conservative unknown-cost reservations. Fairness applies per connection lane; retries count against budgets and cannot rotate accounts to evade restrictions. Existing Google limiter audit findings remain unresolved and must not silently weaken these controls.

Observability separates process liveness, store readiness, worker heartbeat, age of active commands, missing readback, auth failures, event lag and statistics freshness. Do not add a due-post scheduler metric as a hidden execution feature. Content/evidence logging is redacted and access controlled.

Retention proposals remain protected screenshots/DOM seven days, content/receipts ninety days, identity tombstones at least ninety days and longer while remote-queued/unknown or otherwise referenced. Tenant policy governs longer storage; GC requires no live references/holds. Back up SQLite consistently with WAL and immutable asset manifests; keys have independent backup/rotation.

Restore with outbound writes disabled. Reconcile attempted operations against remote queues/items before allowing new commands; never replay a publication because its timestamp passed during downtime. Test disk-full, DB/browser/process loss, clock skew, stale authorization and readback failures.

EventsBot migration: pin donors and compare read/render behavior; stop its local sender for migrated destinations; inventory all local and native pending work. Existing native schedules are adopted as facts without republishing. Any old locally scheduled intent requires explicit migration into the provider queue now while timing/rights permit. Record exact identities and retire the old sender before new ownership. Shadow reads only, never shadow writes. Rollback reconciles uncertain operations and never restarts a duplicate local scheduler.

## 11. Implementation and acceptance gates

| Batch | Deliverable | Blocking evidence |
|---|---|---|
| A | Exact schemas, auth/bindings, SQLite ledger/ready commands/events, history/metrics indexes, assets and fake adapters | No timed publication dispatcher; atomic event persistence; cross-destination denials including cache; restart/CAS/identity tests |
| B | Independent Telegram/VK native queue/read/edit/cancel adapters | Exact queue readback, provider preview, safe minimum lead time, queue-to-published mapping, full bound-channel reads |
| C | MAX persistent-profile Web driver | Native queue workflow, one profile lane, per-step progress, wrong-target/auth denial, ambiguous click and restart tests |
| D | Visuals and deterministic compositor | Real selected hash/revision lineage, consent, budget, expiry before native submission; no fake live imagegen success |
| E | MCP/HTTP, skill, history/statistics and incremental status | Real client with/without progress tokens; prompt initial receipt; first available child event; bounded waits and cursor replay; weak-agent corpus |
| F | DevCoveer canaries and controlled migration | Schedule then stop all VibePublish processes; provider still posts; remote preview/edit/cancel; revoked binding denial; no duplicate sender |
| V | Original video-story feature | Its own render/rights/approval gates; resulting assets use this same native-only social contract |

Required adversarial cases include: successful Telegram native scheduling while MAX hangs; all-target preflight with visible intermediate stages; disconnect during upload; crash before/after dispatch; duplicate and conflicting keys; same channel via two sets; selection closes native timing window; queue full/unsupported surface; missing queue item not equated with sent; manual reschedule; cancellation races; grant revocation and stale cache/cursor; full bound queue including external editors; forbidden unrelated/public channel; owner arbitrary provider-visible chat; leaked cross-link; cached metrics labelled with age; partial refresh; scheduled/published ID changes; restart with no due-time dispatcher.

The design's offline schema/fixture tests are not runtime, provider, browser, latency or weak-model evidence. Live capabilities remain unproved until the corresponding gates run. No Codex is used in the current design correction; later environment/MAX/imagegen integration retains the existing delivery split.

## Official references checked 2026-09-04

- Telegram native queues, edits/deletion and distinct scheduled/sent IDs: https://core.telegram.org/api/scheduled-messages
- MCP progress tokens, optional notifications and active-request lifetime: https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress
- MCP transport/version compatibility: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports

These references support protocol semantics, not a claim that the VibePublish adapters or target MCP client have been tested live.
