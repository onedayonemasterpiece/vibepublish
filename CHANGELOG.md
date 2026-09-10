# Changelog

## [Unreleased]

### ChatGPT OAuth and unattended TLS readiness — 2026-09-06

- Add opt-in MCP SDK OAuth2.1/DCR/PKCE owner consent, resource-bound expiring
  credentials, durable refresh rotation/replay revocation and current-authority
  fencing, without replacing existing scoped bearer access or publishing core.
- Wire isolated stand OAuth persistence; add real HTTP/MCP and launcher security
  regressions and dedicated connection instructions.
- Fix real-browser consent Origin/referrer and exact-callback CSP behavior; verify
  public Chromium consent/PKCE,8tools, original import, refresh, real service
  restart persistence and revocation. Actual owner ChatGPT linking is not claimed.
- Verify the already deployed shared controller reproduces the active exact-host
  nginx config; correct stale claims that domain persistence was still missing.
- Switch only VibePublish certificate renewal to HTTP-01; staging renewal and
  actual nginx-t/graceful reload hook pass without browser/cloud credential auth.


### VK copied-photo identities and explicit unknown recovery — 2026-09-05

- Bind VK user-upload IDs to community-copy IDs using ordered, exact provider
  rendition fingerprints captured before dispatch; reject missing/changed proof.
- Add bounded unauthenticated CDN reads and retain source hashes separately from
  provider bytes; existing stable-ID verification stays unchanged.
- Preserve verified attachments explicitly on VK wall.edit/reschedule; reject
  non-whole-minute VK schedules rather than silently accepting provider rounding.
- Verify live VK native post10 preview/publish/edit/reschedule/cancel, then real
  post11 SIGKILL/restart recovery with one dispatch and no duplicate; cancel both.
- Add owner-only read-only reconciliation for an externally removed uncertain
  VK schedule, with schema-v4 immutable evidence and actor/binding epoch fencing.
  Original unknown operation and attempt remain unchanged; no publication retry.


### Ordinary Codex tasks, chat files and immediate/default execution — 2026-09-05

- Honor explicit visual execute now when no time is supplied, or native scheduling
  in Kaliningrad; keep preview/standalone/human selection and VK stand restrictions.
- Add ordinary Codex app-server image tasks using owner login/quota, Luna, native
  artifact verification and read-only recovery without uncertain resubmission.
- Add native MCP file inputs/import-only publish scope; verify real HTTPS import
  and durable replay without making users upload manually to an HTTP endpoint.
- Fix numeric usage, failed initialization cleanup and protected-root traversal;
  preload trusted skill instructions without changing sandbox protections and
  bound transient read-only observation retries without generation resubmission.
- Verify actual two-source composition through MCP into Telegram native queue8473,
  and immediate generated group message35834, with visual readback, same-key
  replay and restart persistence; retain failed
  operation history and outstanding acceptance gaps rather than declaring full CI.


### Prompt-first postponed visuals and original uploads — 2026-09-05

- Add prompt-only generate/tune/compose inputs with optional references and
  backward-compatible brief/copy; permit automatic selection only for authorized
  future native queue execution, without elevating preview/standalone/immediate.
- Add authenticated idempotent binary original upload with private sanitized
  assets, no AI, route-specific20MiB limit and bounded background decoding.
- Wire owner-approved VK lovekenig postponed-only; record actual copied-photo-ID
  readback blocker and verified one-off test cleanup without resubmission.
- Record417 passing local tests and199 subtests, actual HTTPS upload/schema
  readback, and unresolved automatic executor/attachment-bridge acceptance.

### Isolated DevCoveer implementation and live checks — 2026-09-05

- Add dedicated exact-host server and approved-session Telegram worker launchers;
  develop opt-in Codex image adapter without restoring archive payloads.
- Permit narrow creator-owned basic-group immediate publication; correct null
  cancellation timestamp projection without changing native history or schemas.
- Record real Telegram album/custom emoji and native scheduled lifecycle,
  HTTPS MCP/token delivery, 375 passing local tests and199 subtests (not full CI).
- Record unresolved automatic imagegen, VK destination and shared-ingress
  regeneration durability rather than claiming complete acceptance.

### Core convergence: MAX lifecycle and recovery — 2026-09-10

- Fixed: bounded native MAX browser read budget and precise read-deadline errors; API read limits unchanged.
- Added: authenticated exact MAX own-reaction reads, distinguishing observed removal from missing metadata.
- Added: exact authorized-source download binding for native MAX media forwards without re-uploading.
- Admit bound-subject replies/reactions through the existing worker with explicit
  additive owner-granted rights and exact relationship/own-reaction verification.
- Retain authorized MAX forward source refs and check native attribution/content/media.
- Do not serialize a cancelled native snapshot as a pending schedule with null
  requested time; project old committed cancellation receipts without rewriting history.
- Bind MAX reschedule native ID replacements to original fingerprint and exact
  observed time/content/media without retrying Save or widening other providers.
- Finalization carries the committed observation separately from immutable
  pre-effect evidence, including native IDs first learned during recovery.
- Trusted, checkpoint-bound no-input proofs can cancel an original intent without
  fabricating a remote item or resetting dispatch history; existing durable
  post-commit finalization releases its exact quarantine across restart.
- Delivery receipts expose the explicit additive compensation outcome.
- Canonicalize MAX bold/italic spans around neutral raster emoji graphemes,
  preserving exact text/link evidence and unchanged Telegram/VK semantics.
- Added typed ordered downloaded-media evidence distinct from native attachment
  IDs and uploaded source hashes, with explicit immutable-intent binding.
- Added opt-in MAX semantic styles/links with exact entity verification and
  immutable edit/adoption preservation; Telegram/VK defaults remain unchanged.
- Added owner-only bounded local MP4 ingress with actual decode, metadata removal,
  source lineage, quota checks and preserved video roles; native adapters opt in
  explicitly. FFmpeg is now a CI fixture prerequisite, not a social capability.
- `retry_failed` now re-admits selected original blocked attempts only while
  durable dispatch remains zero, preserving publication revision, immutable
  native CAS and successful siblings; dispatched/unknown effects remain forbidden.
- Standard `worker --native` now lazily selects the optional MAX context factory
  only for approved `max_web` connections; CLI connection provisioning accepts
  that account type. Explicit MAX configuration remains owned by its adapter.
- Added authenticated `publication_update.change.kind=reconcile` for original
  dispatched unknown attempts, preserving operation/revision/plan identity,
  request-key replay (including observation-only re-admission after transient
  unknown evidence), scoped authority and successful sibling receipts.
- Added schema-4 durable evidence/resolution journal and optional idempotent
  provider finalization hook. Quarantine release follows durable resolution;
  pending release blocks connection effects and resumes after worker restart
  without repeating execute. Existing providers remain compatible.

### Owner correction: full Codex rollout includes real Imagegen — 2026-09-05

- Replaced the rejected Telegram/VK-only handoff with a single-link task for local
  Codex on DevCoveer: implementation, real generate/tune/compose, visible candidates,
  selection, compositor, image/emoji publication/readback and persistent deployment.
- Updated active continuation, docs routing and the imagegen runbook so historical
  ChatGPT-stage no-generation/no-deployment limits do not silently shrink the new
  owner-authorized task. Actual platform/access/budget controls remain required.
- Preserved the existing core, tests and separate MAX PR #2. This is documentation
  only: no missing source payload, model call, deployment or new test pass claimed.

### Restore Telegram rich text and VK source — 2026-09-05

- Commit `ae73b259` delivers both exact archived modules through normal GitHub
  writes; 132 of 133 archive paths are present. Only the Codex executor is absent
  after a new request-safety response; no alternate upload was attempted.
- Real core/Telethon gate now passes all 14 requests. Diagnostic execution:
  296 tests and 199 subtests pass, but one Codex import error remains (exit 1).
  Strict full CI stays mandatory; no runtime or test behavior was weakened.
- Updated current status, routing and continuation. Main/MAX and live operations
  were not changed; actual DevCoveer image-only activation remains unverified.

### Recover delivered commits and accepted documentation — 2026-09-05

- Corrected the prior response's false "no new commits" claim: five source
  commits through `18152e5d` added 30 unchanged archive files. Their source/tests
  tree was independently verified from the real CI artifact.
- Read back and attached existing accepted tree `1f36d725` as `76ad2c55`, restoring
  ten documentation changes. No denied source payload was uploaded through it.
- Preserved the remaining historical handoffs and full visual feature description;
  updated current runtime status and continuation rather than creating another plan.
- Re-ran 69 independent tests + 199 subtests in an empty hash-installed venv.
  Full collection still has ten errors; the core SDK gate still fails. Only VK,
  rich-text and Codex executor modules remain absent. No green full-runtime claim.
- No runtime byte changes, weakened tests, MAX changes, model/provider calls,
  alternate-route blocked writes, merge or deployment.

### Actual core source delivery and current access boundary — 2026-09-05

- Read the existing access retrospectives and corrected an overbroad permanent
  write-ban assumption. Standard authorized GitHub source writes succeeded.
- Saved 26 original source/configuration paths in commits `938f303d` and
  `348233a0`; independently matched the complete accepted partial tree hash.
- Later VK adapter and rich-text source requests received explicit request-safety
  evaluation blocks. Their payloads and 46 other pending paths are not delivered;
  this partial checkout is not a runnable or deployable full application.
- Preserved the mandatory full-runtime CI instead of claiming seed-only green
  checks prove delivery. Updated canonical status and concise delivery proof rule.
- No blocked payload retry via another route, agent delegation, MAX change,
  provider/model call, merge or deployment.

### Locked environment and real core SDK regression — 2026-09-05

- Pinned the independently qualified 70-package graph for Linux Python 3.12/3.13;
  normal hosted CI installs the committed lock. Added six input/include regression
  tests. Qualification CI 33953694373 succeeded on both versions.
- Full LOCAL core passed 327 tests + 199 subtests in a clean hashed-wheel environment.
  Added 19 real SDK/core tests; fixed the old >8-byte SDK gate (valid config is 8).
- Direct runtime pins unchanged; explicitly qualified transitive SVG updates:
  cssselect2 0.10.1 and webencodings 0.6.1, plus optional SDK/browser/build pins.
- Full core/source and its mandatory runtime CI remain local. No protected upload,
  MAX change, delegated task, real generation or deployment.

### Dependency and native SDK qualification — 2026-09-05

- Added an independent real Telethon 1.44 wire-roundtrip gate (14 request kinds,
  exact custom emoji IDs and UTF-16 spans), without credentials or provider RPCs.
- Added dependency graph/wheelhouse validation and 10 regression cases; extended
  the same hosted CI to empty Python 3.12/3.13 environments and exact hashed,
  offline reinstallation. Both jobs succeeded in run 33953694373; source artifact bytes were read back.
- Corrected the local pip diagnosis: DNS failure is not package nonexistence.
- No protected core payload, MAX implementation, agent or model call is included.

### Telegram custom emoji workflow and continuation — 2026-09-05

- Recorded required emoji-set links, private numbered previews, exact single or
  ordered-chain selection, personal aliases/rules, frozen semantic entities and
  pre-publication compilation; detailed workflow is Draft, runtime Not done.
- Read actual EventsBot transformer/tests and composite-ID/medallion incidents;
  reuse deterministic behavior, not hard-coded two-unit spans or delayed editing.
- Corrected imagegen execution target to local Codex on DevCoveer, not the owner's
  desktop/OpenCode candidate; generator invocation is not coding delegation.
- Verified the original transfer archive again and recorded MAX PR #2's actual
  fixture-only scope, missing-archive integration blocker and continuation.
- Added one ChatGPT continuation handoff; no runtime code, emoji/live test,
  generation, MAX task, deployment or previously blocked core write performed.

### MAX handoff and imagegen plugin identification — 2026-09-05

- Published the separate MAX Web task against the actual archived shared port,
  with independent MAX commits and explicit offline/browser/live boundaries.
- Verified official Codex imagegen sources and the separately identified
  OpenCode candidate; do not infer the owner installation or requested route.
- Added passive bounded installation inventory and 21 tests. No auth reads,
  plugin imports, agent delegation, generation or deployment.
- Extended the existing GitHub-hosted CI with inventory tests. This does not
  deliver or validate the separately archived full runtime.
- Documented actual GitHub write permissions versus the previous per-call
  OpenAI safety-check block; the new MAX document write/readback succeeded.

### Development handoff — 2026-09-04, contract 1.2.0-design

- Added canonical native Telegram/VK forwarding by exact post URL or authorized
  item reference, with attribution readback, grouped-media handling, private-source
  authorization and no rewrite/copy fallback. VK scheduled repost remains an
  unproved capability, not a local-scheduler substitute.
- Extended the existing engage command schema; no new forward synonym tool.
- Added personal primary/secondary destination profiles with purpose, audience,
  topics, exclusions, notes, explicit/agent selection policy and CAS revision.
  Profiles do not change provider identities or grants. Added routing_revision.
- Extended get_started sections with forwarding, destinations and all; retained
  the single bootstrap/skill method and resource/prompt compatibility design.
- Added narrow forward and destination.profile catalog projections without
  granting unrelated engagement or destination administration operations.
- Added automated acceptance matrix with actual versus planned test boundaries,
  core/MAX ownership, live native-queue shutdown and native-forward canaries.
- Added ready-to-use files for a new ChatGPT core implementation window and a
  separate bounded Codex MAX Web implementation task. Neither task was launched.
- Reran the existing 14 contract methods, then all 22 methods successfully after
  changes: 16 schemas, 125 golden calls and 44 negative calls. New cases are in
  tests/contracts/test_forwarding_profiles_design.py; runtime-oracle labels are
  not counted as executed runtime checks.
- Canonical skill text update was blocked by the connector and did not commit.
  The skill file remains v1.1; its v1.2 synchronization is an explicit core-batch
  prerequisite recorded in docs/README.md/routes and the latest requirement
  extension. The new schema/test and handoff files were saved successfully.

### Owner correction — 2026-09-04, contract 1.1.0-design

- Replaced the rejected local publication scheduler/default/fallback with native
  Telegram/VK/MAX queue submission, provider preview/readback and native edits,
  reschedules and cancellations. Removed backend/late fields and service-queued
  observations from the executable contract. MAX remains Web/Playwright.
- Separated the immediate command executor and persistent history from any future
  send timer. Provider execution after VibePublish shutdown is an explicit live
  acceptance gate. Revocation does not silently cancel existing native schedules.
- Added prompt accepted receipts, required progress events/cursors, per-provider
  stages, bounded first-event status waits and recovery semantics. Optional MCP
  notifications are not assumed visible to every agent/client.
- Partner read access now follows active publishing bindings and includes all
  provider-visible posts and native scheduled items in those channels, including
  other editors' posts. Unrelated channels/dialogs remain inaccessible; the owner
  retains provider-visible unrestricted discovery/reading. Cached/private-data
  boundaries and revocation are explicit.
- Added indexed publication history and exact-publication cached/refreshed
  statistics queries with observation timestamps and provenance. Queue reads
  remain live provider reads, not a local-history projection.
- Updated canonical requirements, implementation design, MCP contract, skill,
  routing, executable schemas and fixtures. Historical audit/handoff choices
  superseded by these owner corrections are explicitly identified as historical.
- Fourteen offline contract test methods passed: sixteen input/output schemas,
  105 golden calls and thirty invalid calls, including progressive mixed-child
  receipts, native-only inputs and six-tool active-partner projection.

### Earlier design checkpoint

- Independent architecture/product/security audit with twenty design findings
  and five targeted existing Google limiter findings.
- Independent social-service ownership, immutable revisions/idempotency,
  provider readback, MAX state-machine boundaries, recovery and donor cutover.
- Initial eight-tool schema design, eighty golden calls, twenty invalid calls,
  eight offline tests and a versioned skill. The earlier service-scheduler and
  separate partner-read-grant decisions were subsequently rejected as above.
- Social visuals contract preserving the required imagegen route, exact text,
  candidate selection and consent-controlled provenance.
- Video-story feature preserving Telegram editorial control, Kaggle rendering,
  geo/time filters, music, subtitles, enhancement and approval.
- Standalone scaffold, feature documentation routing, existing Google AI /
  Supabase limiter code/migrations and EventsBot donor map.

### Verification boundary

- This work changes requirements and executable design/tests, not social runtime,
  provider adapters, database migrations or deployment.
- No Codex task, live provider operation or image generation ran. Native queues,
  actual MCP incremental delivery, MAX Web, imagegen, runtime permissions,
  database concurrency and infrastructure-independence canaries remain unrun.
- Existing Google limiter findings are documented, not fixed by this batch.
- Schema-valid forbidden calls carry runtime-oracle requirements; schema tests
  do not claim that an absent runtime enforced those permission/timing rules.
