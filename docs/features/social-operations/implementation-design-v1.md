# VibePublish — implementation design v1

Date: 2026-09-04. Reviewed base: `a2a089f320049b6413cd2f635fd8e93ab7aee888`.

Owner requirements: `Fixed`. New engineering choices in this document: `Not confirmed by user`, selected for implementation rather than represented as owner-approved. Runtime: `Not done`.

This is the technical continuation of [the canonical feature](README.md). It supersedes the candidate taxonomy and unresolved engineering alternatives in [the historical handoff](analysis-handoff-20260904.md), not the owner's corrections. No Codex task, provider write, credential inspection or deployment was performed for this design.

## 1. Product and scope

The product is a dependable social-operations service, not an autonomous social-media agent. The agent decides editorial intent; deterministic services enforce identity, permissions, media, timing and evidence. Success means the requested content reaches the requested destination with an honest, recoverable receipt.

Two separate scope levels prevent a thin pilot being called the complete product:

- **First usable publishing slice:** Telegram, VK and MAX Web; exact destinations and sets; text plus ordered images/video; service scheduling; supported edit/reschedule/cancel/delete; partial delivery; scoped external principals; receipts and recovery; generated/tuned images with choice.
- **Full committed baseline:** all donor-compatible reading, stories, rich media, messaging, forwards, comments, reactions, analytics, native schedules and ownership-verified connections. Unsupported capabilities are explicit, not erased. The video-story generator is an additional feature, not a second social backend.

Not every provider must support every surface. A function is advertised as working only for a proven connection/destination/surface combination. The public tool taxonomy can describe an operation before a connection supports it, but bootstrap must report the actual capability and rejection must precede provider mutation.

### Requirement classification at audit

| Already present | Needs clarification, now decided | Missing, now specified |
|---|---|---|
| Independent service; three providers; one publish call; opaque aliases; per-target receipts; unknown-outcome handling; imagegen correction; broad donor baseline | Tool taxonomy; external read defaults; native versus service scheduling; partial fan-out; media readback meaning; visual selection versus approval; single-owner versus tenant isolation | Request/plan digest split; immutable set snapshots; durable dispatch point; bounded MAX recovery; cancellation races; revocation of native schedules; security threat model; operational recovery; acceptance matrix; video feature routing |

## 2. Chosen architecture

One Python application, two supervised processes, one domain model:

```text
MCP / HTTP / Telegram editorial UI / EventsBot
                 |
             API + authorization
                 |
       application services + SQLite/WAL
                 |
           durable task worker
      /          |           \
 Telegram       VK       MAX Web driver
                 |
       optional visual/video jobs
```

API responsibilities: authenticate, resolve identity, validate closed schemas, import bounded assets, persist intent, expose receipts and authorized artifacts. Worker responsibilities: scheduling, provider execution, reconciliation, visual jobs and notifications. Neither transport owns business state. Request disconnection does not cancel an accepted operation.

Use Python 3.12 for the first deployment; lock the exact dependencies and browser binary during implementation. Use the maintained MCP SDK and an ordinary HTTP framework over the same handlers. Do not implement MCP wire framing or OAuth cryptography by hand. Support only protocol versions actually demonstrated with the selected SDK and target clients; current specification review used 2026-07-28. Keep durable operation IDs independent of MCP transport IDs, connections and protocol sessions.

SQLite is local persistent storage, not a network-mounted shared database. Enable foreign keys, WAL, busy timeout and explicit short write transactions. Persist before external I/O; never hold a database transaction while waiting on a network or browser. A durable tasks table is the outbox; a second broker/Redis/PostgreSQL installation is unnecessary for this deployment. Optional existing Supabase Google quota accounting is not the social ledger and is not required for ordinary publishing.

### Planned modules and ownership

| Module | Owns | Must not own |
|---|---|---|
| `social_operations/domain/` | entities, transitions, digests, invariants | SDK, browser, transport auth |
| `social_operations/services/` | authorization, publishing, lifecycle, reads, visuals, destinations | direct provider SDK calls |
| `social_operations/storage/` | SQLite repositories, migrations, task claims, receipts | business exceptions hidden as success |
| `adapters/telegram/`, `adapters/vk/`, `adapters/max/` | provider capability checks, execution, readback | tenant grants, model-driven business decisions |
| `adapters/imagegen/` | bounded external executor contract | destination or publication decisions |
| `mcp/`, `api/` | schema projections and authentication adapters | duplicate application logic |
| `worker/` | claims, scheduling, reconciliation, notification delivery | another source of publication truth |

## 3. Data model and transaction boundaries

IDs are opaque random service IDs. Every externally addressable resource carries `tenant_id`. Repository methods require an authenticated principal context; neither an ID nor a content hash is authorization.

| Entity | Mandatory data / constraints |
|---|---|
| tenant, principal, credential | status, policy epoch, hashed service credential, expiry; provider tokens are separate encrypted records |
| connection | provider, account identity, owner tenant, encrypted secret/profile reference, status, authorization epoch, connection-wide cooldown |
| destination + binding | immutable provider identity; tenant-scoped unique alias; exact connection binding; granted operations; provider-rights observation |
| destination_set + members | tenant-scoped unique alias, revision, explicit destination IDs; nested sets prohibited in v1 |
| publication + revision | author principal, request identity, semantic content, requested schedule, immutable normalized plan and plan digest |
| delivery | publication revision, frozen destination/binding/surface, planned backend, desired state, observed state, current attempt; unique target per revision |
| operation + attempt | command identity, CAS revision, actor, durable phase, provider request identity, dispatch-start timestamp, lease/fence, error class |
| task | operation reference, due time, lease owner/expiry/fence, attempts, next eligible time; durable queue and notification outbox |
| asset + derivative | tenant, digest, MIME/size/geometry/duration, immutable storage path, provenance, rights/retention metadata |
| visual_job + candidate + decision | exact executor request, source/output digests, selected candidate, review binding, feedback and training permission |
| approval | hashed single-use token, tenant/principal, publication revision, plan digest, expiry and policy epoch |
| quota reservation | tenant + connection + operation dimensions, estimate, actual usage, terminal/unknown accounting |
| evidence | operation/delivery binding, evidence kind, observation time, protected storage ref and retention class |

Composite tenant-aware foreign keys or equivalent mandatory repository checks prevent cross-tenant linking, including assets, candidates, parent jobs and receipts. Append attempts and revisions rather than overwriting previous evidence.

**Accept transaction:** resolve and authorize the entire target set, allocate operation identity, persist the initial immutable request and task. Before final dispatch, freeze imported asset hashes, rendered variants, selected visual and capabilities into an execution revision. A source that cannot be imported leaves a durable failed/blocked operation, not an unrecorded upload attempt.

**Claim transaction:** one eligible task becomes claimed using compare-and-set; increment fencing token. Workers recheck the token and authorization immediately before dispatch. A fence prevents stale database updates but does not retract a remote network request. Consequently no worker may take over an already `dispatch_started` side effect merely because a lease expired.

**Completion transaction:** store observation, evidence and per-target result, recalculate the parent projection, create notifications. Notification failure never changes a publication into a publishing failure.

## 4. Publication semantics

### Content and destinations

Normal calls use registered aliases. Alias and set names occupy one tenant-scoped namespace. `to: ["pka"]` may resolve a set; its concrete members and versions are frozen when accepted. Later set edits cannot redirect an existing queued publication. Deduplicate overlapping sets by immutable destination identity and surface.

The model may submit plain text or a documented bounded Markdown subset. The service compiles it to a semantic document and provider renderings. Do not require the agent to count UTF-16 offsets, construct Telethon entities or stage uploads. Explicit per-provider renderings remain possible. Unknown formatting and unsupported entities are rejected or explicitly degraded in preview, never silently removed during dispatch.

Default adaptations are deterministic. Optional model rewriting produces a new reviewable revision and cannot alter facts, links, destinations, media or timing in the dispatch phase. Telegram named links/custom emoji and VK explicit URLs remain provider-specific. MAX named-link support is capability-gated by observed UI behavior. Platform length, entity-offset and caption/media-group constraints are validated by versioned provider rules; no global hard-coded minimum hides richer capabilities.

Media order is binding. No silent truncation, image omission, unexpected multi-post splitting or replacement with a generated picture. If a provider requires splitting, preview lists every resulting item and approval binds that expansion. Normal v1 rejects a nontrivial split until explicitly authorized.

### Fan-out policy

Preflight **all** targets, permissions, capabilities, media constraints and renderings before the first send. Default: any deterministic validation error blocks the entire request. After dispatch begins, providers are independent: runtime failure of MAX must not erase successful Telegram/VK publication. Do not attempt cross-platform rollback or promise atomic delivery.

Successes are immutable evidence. Retry only failed children proven not to have applied; never repeat verified or uncertain children. A revision edited after partial publication reports per-target revision; the UI must not imply all targets contain the latest revision.

### Request identity versus execution identity

Use two digests, not one self-contradictory hash:

1. **Request digest:** authenticated identity, normalized caller arguments and stable source references. Explicit `request_key` is unique per tenant/principal/command; exact replay returns the original operation before re-fetching URLs or re-resolving sets. A conflicting payload under the same key is rejected.
2. **Plan digest:** frozen destination identities/bindings, semantic and rendered content, ordered imported asset hashes, surface, UTC schedule/backend, preset version and accepted visual choice. Approvals and dispatch attempts bind this digest and revision.

A generated image does not exist when the initial request arrives. Candidate selection therefore creates a new execution revision; it does not mutate the original idempotency record or cause an exact replay to generate again.

HTTP deterministic clients must send an idempotency key. MCP may omit it: the server uses a normalized-intent duplicate window of 24 hours within the principal, excluding volatile request timestamps. Replays within this window return the previous receipt without a new send. Repeated identical content with a new key is still checked as a duplicate candidate. Intentional repetition requires an explicit `repeat_of` reference and a fresh request key. This is a product guard, not a claim of universal exactly-once delivery. Retain key tombstones for at least 90 days and longer than any pending/uncertain operation or scheduled job; expired identity history must never silently authorize a recovered unknown attempt.

## 5. Scheduling, edits and cancellation

**Default scheduler is the VibePublish durable queue**, for all three providers. This keeps rights revocation and late policy consistent. Provider-native scheduling is an optional explicit backend and is enabled only after its creation, discovery, reschedule, cancellation and post-due reconciliation canaries pass. Store one backend per child; never have two schedulers own the same send. Never fall back from a possibly accepted native schedule to a service schedule.

Require an RFC3339 timestamp with offset for a scheduled call. Bootstrap returns the tenant's configured IANA zone and server time; it does not borrow the ChatGPT browser timezone. Resolve relative language before the mutation. An absent tenant timezone plus ambiguous local time requires clarification rather than a guessed offset. Display requested local time, normalized UTC, effective backend and observation time in the receipt. DST gaps/folds, nonexistent dates and past timestamps are validation errors.

Late default: `hold`. An explicitly selected `send_within_15m` permits dispatch up to 15 minutes after due time, never after an event-specific expiry supplied by the client. Re-check at actual dispatch, including browser queue delays. Expired jobs are held and notified, not silently sent hours later. New auth or visual selection after due time does not reset the schedule to now.

Edits, reschedules and deletions require the current publication revision. Re-read the provider item before mutating; compare the observed fingerprint/revision with stored evidence. Changes made manually outside VibePublish produce `external_change` rather than an overwrite. This is optimistic conflict detection, not a claim that every provider implements an atomic CAS.

`cancel` means prevent unperformed delivery; `delete` means remove an already published item. Cancellation racing with dispatch becomes `cancel_requested` internally until observation establishes which state occurred. A published result must not be labelled cancelled. Native cancellation needs provider-backed evidence; local tombstones alone are insufficient. Post-publication deletion requires the relevant user authority and readback.

Revocation stops undispatched jobs immediately. In-flight operations are reconciled, not retried. Previously submitted native schedules require cleanup using a narrowly scoped internal cancellation authority, audit and notification. If provider access has already disappeared, report `remote_schedule_may_remain`; do not promise that revocation erased a remote scheduled post.

## 6. State machine and honest receipts

Separate three concepts:

- **Desired publication state:** what the user requested and at what revision/time.
- **Operation phase:** validating, awaiting review/selection, queued, claimed, dispatch started, reconciling, terminal.
- **Observed provider state:** not attempted, service queued, provider scheduled, published, edited, deleted, cancelled, absent or unknown.

Public operation states: `queued`, `running`, `needs_approval`, `needs_selection`, `scheduled`, `verified`, `partial`, `failed`, `outcome_unknown`, `cancelled`, `held`.

`verified` means the requested operation is verified, not automatically that a post is public. The receipt always states the action and each observed provider state. A verified native schedule is `provider_scheduled`; actual publication requires a later observation.

Parent projection order: any uncertain side effect makes the parent `outcome_unknown`; otherwise incomplete tasks remain running/scheduled; otherwise mixed applied and failed results become `partial`; all requested target postconditions proven becomes `verified`. Include child counts so uncertainty cannot be hidden behind a friendly aggregate label.

Every mutation response includes operation ID, publication/resource ID where applicable, revision, state, short explanation, per-target observations, evidence references, requested/effective schedule, `retry_safe`, and a finite next action. Reads and bootstrap also use closed output schemas. `next_action` is one of `none`, `check_status`, `approve`, `select_visual`, `fix_input`, `refresh`, `reauthorize`, `review_outcome`, `contact_owner`. Errors distinguish pre-dispatch rejection from an accepted uncertain operation.

Persist `dispatch_started` **before** the side effect. Crash after that boundary is potentially applied even if no response was saved. Provider-specific stable idempotency IDs may be reused only where their semantics are proven. Missing readback is not proof of nonpublication. Search results or an old identical post alone do not prove success. Never repeat an uncertain browser click.

### Media evidence

Source asset SHA-256 proves what was supplied, not byte equality after provider recompression/transcoding. Track separately: source hash, uploaded-provider object identity when available, delivered item identity, count/order/type/dimensions/duration, rendered text/entities and provider observation. Label byte match, provider-object binding and visual/semantic correspondence as different evidence levels.

Default media verification requires target identity, exact rendered text/links, correct media count/order and a supported asset-binding method. If a platform cannot prove part of this, receipt says `verification_incomplete` with the specific missing check; it must not invent a remote SHA or mark the stronger guarantee passed. Incomplete verification after possible publication prohibits an automatic repost.

## 7. MAX Web: concrete driver contract

MAX remains Web/Playwright. No API approval dependency and no MAX API client in this release. `my-browser-bridge` is a diagnostic tool, not a required production publishing backend.

One persistent profile belongs to one provider connection. Use a dedicated encrypted-at-rest volume, restricted process user and permissions. Multiple tenants may receive narrowly bound publishing rights through the same operator connection, but no tenant sees its browser state, unrelated DOM, other dialogs or session export. One process holds the profile lock; one serial side-effect lane per profile/account. An expired database lease never permits simultaneous browsers against the same profile.

Driver transitions:

```text
CHECK_SESSION -> OPEN_EXACT_TARGET -> VERIFY_TARGET_ID
-> OPEN_COMPOSER -> FILL_TEXT -> UPLOAD_ORDERED_MEDIA
-> VERIFY_COMPOSER -> DURABLE_DISPATCH_STARTED -> SUBMIT_ONCE
-> REACQUIRE_TARGET -> LOCATE_RESULT -> VERIFY_RESULT -> RECEIPT
                                      \-> RECONCILE / OUTCOME_UNKNOWN
```

Before submit verify stable target identity, account identity, text/link representation, count/order of uploaded previews, readiness indicators and schedule/timezone if native UI scheduling is used. Display names are insufficient. Pin a known origin and verify navigation does not land in another account/channel. Never use an unchecked `nth()` match or click-by-coordinate as the primary targeting method.

Use role/label/text locators scoped to a uniquely identified dialog/container; re-acquire locators after DOM updates. Deterministic recovery may reload or reopen a composer **only before** the durable dispatch point and must reconstruct from the immutable plan. After that point all recovery is observation-first. Handle virtualized feeds, stale dialogs, target renaming, delayed media processing and identical recent posts explicitly.

Readback must establish the new item identity/permalink where available and inspect the item in the target feed, not just the composer or success toast. Store a protected evidence bundle: target identity observation, sanitized pre-submit state, ordered-media evidence, post-submit item observation, timestamps and driver version. If no durable remote ID is exposed, use a bounded candidate search with exact content/media/time/author evidence; ambiguous or multiple matches remain unknown.

Default bounds proposed for implementation: 90 seconds for an immediate MAX attempt, at most two pre-submit recoveries; reconcile after 5, 30 and 120 seconds, then passive checks up to 24 hours. These are configurable operator budgets, not guarantees. Per-profile fairness prevents one tenant monopolizing the lane. Stop on login expiry, QR/OTP/CAPTCHA, permission loss, changed target identity, duplicate candidates or exhausted budget. Authentication challenges require a human.

Model-assisted DOM recovery is **not in the critical path**. Enable later only for one sanitized, nonmutating locator proposal before dispatch, at most one proposal per transition. It may not execute JavaScript, read secrets, change target/content/time, click submit/delete or resolve unknown outcomes. Private DOM/screenshots must not be sent to a model without an explicit data policy. A disabled recovery model must not disable a healthy deterministic driver.

Offline browser fixtures are useful for crash/transition tests but do not prove MAX works live. Codex/DevCoveer integration later must capture real UI fixtures and run designated-channel canaries; no live test channels are assumed or invented here.

## 8. Authorization, assets and quotas

Effective write authority = active principal AND explicit operation grant AND destination binding AND valid connection AND current provider permissions AND approval policy. Enforce it on MCP, HTTP, worker dispatch, status, asset downloads and candidate selection. Hiding a tool is usability, not security.

Owner reads may resolve any resource genuinely visible to the connected owner account. External principals have **no social reading by default**, including with their own connection, until explicit destination/operation read grants exist. They may inspect their own publications and narrowly scoped operational receipts. Internal readback for their writes must not expose surrounding feed/history.

Own-credential onboarding and operator-shared credentials remain distinct. External users never submit secrets in model arguments. Owner CLI issues short-lived single-use onboarding links or accepts secret-store/stdin inputs. OAuth where available, supervised session provisioning otherwise. MAX QR/OTP login is performed by the authorized human in the isolated profile. Operator-shared destination bindings are created only by the owner after checking the provider account's publishing rights. Supplying a URL does not create a grant.

Service authentication and upstream provider authentication are separate. HTTP MCP validates issuer, audience, expiry and scopes using a proven OAuth implementation; service clients use scoped, hashed/revocable credentials. No token passthrough to providers; no tokens in URLs. Revocation increments a policy epoch checked by pending work. Cache bootstrap by principal, policy epoch, skill/schema version and capability observation time, not globally.

Asset ingress supports owned service asset refs, approved HTTPS downloads and authenticated application uploads. A local ChatGPT path is not assumed reachable by DevCoveer. The host/application must import the attachment or provide a valid signed URL; otherwise return `media_unavailable` before any send. No model-visible stage/commit choreography is required, but bytes still need a real transport.

Ingress defense: resolve and pin allowed public addresses, recheck every redirect, block private/loopback/link-local/metadata networks and credentials in URLs, apply fetch deadlines and byte/decompressed-pixel/duration limits, sniff MIME, decode in a constrained process, sanitize filenames, remove unsafe metadata from outward derivatives and prohibit executable/raw SVG uploads as active content. Authenticated provider fetches use a separate allowlisted adapter path, not the generic URL downloader. Preserve immutable original media under access control; EXIF coordinates for the video feature are private metadata, never automatically published.

Tenant-scoped asset handles and authorization checks precede cache/dedup lookups. A guessed SHA must not disclose another tenant's content or existence. Signed download/preview URLs are short-lived and bound to authorized resources; avoid public evidence URLs.

Quota dimensions: principal/tenant publication count, concurrent jobs, generated candidates, stored bytes, outbound bytes and connection-wide provider limits. Reserve before costly work, settle actual usage, retain an unknown-cost reservation after an ambiguous external generation. Retries consume attempt budgets, not a fresh user publication quota. Use weighted/round-robin tenant fairness within a shared connection lane. Never rotate accounts to evade a provider restriction.

All provider text, comments, captions and files are untrusted data. They cannot expand grants, modify the task, request tool calls or authorize a publication. Test prompt injection through comments, filenames, HTML, metadata and images.

## 9. Operations and migration

Deployment config must include the dedicated `VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE`, namespaced VK secret references, encrypted MAX profile path, persistent DB/assets paths, encryption key references, tenant zone, retention policy and quota configuration. Fail startup on missing mandatory configuration for an enabled adapter. Report disabled/missing-auth connections explicitly rather than probing unrelated credentials.

Health endpoints separate process liveness, DB readiness, worker heartbeat, queued lateness and provider capability freshness. Metrics: accepted-to-verified latency by provider, oldest due job, unknown outcomes and age, duplicate prevention, media mismatch, auth/captcha events, queue fairness, recovery attempts and generation spend. Redact secrets, session IDs and private content from ordinary logs.

Proposed retention defaults: protected DOM/screenshots 7 days; content/receipts 90 days; idempotency tombstones at least 90 days; referenced assets retained while queued/unknown or inside the tenant retention period. Operator policy may extend retention. Garbage collection requires zero live references and no legal/explicit preservation hold. Encryption keys have independent rotation and backup procedures.

Back up SQLite with a consistent backup API/checkpoint procedure and assets by immutable manifest; do not copy only the main DB file while WAL is live. Restore onto an isolated instance with outbound writes disabled. Reconcile every dispatch-started operation before enabling delivery. Test database loss, disk full, process kill, browser kill, clock shift and stale auth. Rollback may stop dispatch and revert code but must preserve forward-readable operation history.

EventsBot migration is per destination/capability, never an uncontrolled global swap:

1. Pin donor source and regression tests; port without runtime imports/session fallbacks.
2. Shadow **reads/rendering only**; compare outputs. Never shadow live writes.
3. Freeze old scheduler for the migrated slice; reconcile/import outstanding scheduled items and unknown attempts, including their remote IDs and identity history.
4. Hand one durable execution-ownership marker to VibePublish, route new requests there, verify no second scheduler can send.
5. Reconcile backlog before rollback. Do not reactivate the old writer against uncertain VibePublish operations.

Donor `main` observed in this audit: `2334917ca30f803babad0f593fbffd8ad39fb709`. The donor map is a source inventory, not proof that those features already work in VibePublish.

## 10. Implementation batches and release gates

Every batch includes code, regression tests, docs and a remote readback. The present change is a design package, not completion of these batches.

| Batch | Deliverable | Blocking acceptance |
|---|---|---|
| A | Package/lockfile, schema projection, auth context, SQLite entities, outbox, quota and asset boundaries, fake providers | Contract fixtures; cross-tenant denial; CAS races; crash at every phase; no external sends |
| B | Independent Telegram + VK adapters, publication/lifecycle, exact receipts | Donor parity matrix; ordered media; scheduling backend exclusivity; uncertain-outcome reconciliation; no EventsBot imports |
| C | MAX deterministic driver + fixture tests | Wrong target/account and stale-profile denial; pre/post-click crashes; one profile lane; no duplicate click; partial fan-out |
| D | Visual service, fake executor, deterministic compositor, selection/approval and training-consent lineage | Selected hash preserved; selection authorization; budget/restart tests; exact typography and crops |
| E | MCP + HTTP over the same services, versioned skill, full read/engagement/analytics capability projection | Real weak-agent benchmark; auth-filtered catalog; transport compatibility; API/MCP parity; bootstrap token budget |
| F | DevCoveer integration and live canaries, then controlled EventsBot migration | Real MAX Web; independent credentials; actual `$imagegen` artifacts; scheduled-to-published transition; edit/delete and recovery evidence |
| V | Video-story editorial pipeline | See [video stories](../video-stories/README.md); Kaggle render, rights and approval, then existing publication service |

First implementation work remains direct ChatGPT/GitHub work unless the owner changes that instruction. Codex is reserved for the later environment integration/live-driver and imagegen verification stage; this audit did not invoke it.

### Required tests (not claimed executed by this document)

- Concurrent identical request, conflicting key, new key with same content, intended repeat, key retention and mutable source URL.
- Set membership/alias/binding change between queue and dispatch; same target through two sets.
- Connection/grant revocation at acceptance, after visual generation, while queued, immediately pre-dispatch and after native scheduling.
- Cross-tenant operation, asset, candidate, approval, search, pagination, evidence and cache access.
- Provider timeout before sending versus after sending; crash before/after durable dispatch; stale worker fence; observation arriving after timeout.
- Telegram success + VK failure + MAX unknown: no repost of Telegram and parent uncertainty visible.
- Native schedule readback versus actual post; DST ambiguity; late browser lane; expired event; cancel/send race; external manual edits.
- Media count/order/entity offsets, provider transcoding, caption overflow, malicious URLs, redirects and decompression bombs.
- MAX identical recent posts, virtualization, failed upload, wrong account, auth challenge, selector drift and browser restart.
- Visual selection replay, stale approval, wrong-tenant candidate, generation timeout, selected derivative substitution and missing training consent.
- Backup/restore with writes disabled; cutover with old queue drained; rollback without duplicate execution.

Offline fixtures and schemas prove determinism and contract consistency only. Live provider behavior, real weak-agent accuracy and `$imagegen` availability are separate evidence gates. No provider capability, performance percentile, model benchmark or production readiness is asserted without its actual run.

## References

Repository evidence is pinned in the [audit](../../reports/vibepublish-audit-20260904.md). Official documents checked on 2026-09-04:

- MCP tools and JSON Schema: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- MCP authorization: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- MCP security: https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices
- Playwright locators/actionability/auth: https://playwright.dev/docs/locators ; https://playwright.dev/docs/actionability ; https://playwright.dev/docs/auth
- Telegram scheduling: https://core.telegram.org/api/scheduled-messages
- SQLite WAL: https://www.sqlite.org/wal.html
- PostgreSQL locking (existing optional limiter): https://www.postgresql.org/docs/current/explicit-locking.html
