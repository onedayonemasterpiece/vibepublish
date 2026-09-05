# Changelog

## [Unreleased]

### Fixed
- MAX actual-core test subprocesses preserve the explicit Playwright browser
  installation path while still scrubbing credentials; the early-progress
  assertion deadline is unchanged.
- MAX rejects unfinished live mutations before touching the composer or dispatching;
  missing causal receipts cannot be enabled by an ad-hoc publishing flag.
  Preserves unknown-attempt quarantine during read-only reconciliation.
  One experimental live text attempt remains unknown and uncleared; this is not
  publishing/lifecycle acceptance (see the MAX runbook).

### Added
- MAX exact-reference read-only recovery, explicitly bound to the original
  attempt/digest through the actual core port. Repeated UI observation preserves
  unknown state/quarantine; terminal resolution remains a core dependency.
- Same-driver native-reference/order/drift replay (including reordering inside
  awaited account callbacks) and real reader-process
  crash/restart coverage, with no Send or profile unlock.
- MAX observed-UI read/navigation subset, explicit existing-session read-only factory,
  private structural export, and mandatory Chromium navigation/order-drift replay.
  Live reads cover the three clarified destinations; publication/queue identity/
  full lifecycle and real-driver core integration remain unimplemented.
- MAX MCP test transport now aligns HTTPX read timeout with its explicit long-poll
  budget; the separate first-event deadline and dispatch/crash assertions stay intact.


### Task prepared — owner-authorized MAX live completion, 2026-09-05

- Added docs/handoffs/max-web-live-completion-20260905.md for continuing PR #2
  through real MAX implementation, live debugging and same-driver GitHub replay.
- Recorded the owner's explicit scope: all social-operation scenarios in
  «Тестовая группа»; feed/queue reads and task-owned scheduled probes only in
  «Ух ты, Калининград!» and «Полюбить Калининград». Existing editorial content
  remains read-only. Exact target binding, safe timing and cleanup are required.
- Reuse the already authenticated MAX session; no login debugging now. Future
  QR onboarding is documented separately, not implemented by this package.
- Added L01–L16 acceptance cases, positive functional outcomes, all six target
  permutations and mid-action reordering, DOM/media failures, protected replay
  fixtures, no live MAX network/credentials in CI, and exact-SHA reproduction.
- Updated the task route and MAX runbook so historical live prohibitions do not
  contradict the new limited authorization. Prior offline evidence is retained
  by pinned reference. No runtime code changed, no agent/live tests were launched.

### Added — MAX canonical bridge and local core integration, 2026-09-05

- Verified the supplied 103-source core ZIP/bundle/patch and moved it to local
  artifacts; added a reproducible local-only MAX overlay assembler, no core upload.
- Added MAX bridge importing the actual ProviderAdapter port/native helpers:
  typed observations, scoped reads/cursors, proven input-media bindings and
  recoverable attempt/plan checkpoints. Translates driver progress vocabulary to
  core statuses without changing core dispatch/auth/ledger or the common port.
- Added real MCP ClientSession/worker/SQLite + Chromium fixture integration for
  early TG/VK progress, durable marker before effect, SIGKILL/restart without
  duplicate sends, scoped external queue reads and preserved partial successes.
  Original 37 tests and loopback guard remain; absent-core CI skips are explicit.
- Live MAX factory/selectors, text-only attribution, cancel/delete evidence and
  media-preserving reschedule remain unverified; no live actions or deployment.

### Added — MAX-only offline checkpoint, 2026-09-05

- Added a fixture-only deterministic MAX UI driver, process-exclusive profile
  lock, persistent uncertainty quarantine, awaited hooks, native-time/CAS guards
  and scoped saved-item readback. No live profile or runtime adapter is enabled.
- Added real Chromium synthetic fixtures and process-kill/competition tests;
  reused the canonical CI path for MAX checks. These do not prove live MAX.
- Added canonical MAX runbook/capability/status matrix. Archived core ZIP is
  missing in this environment: real port/worker/MCP integration remains blocked;
  no substitute core contracts, live canaries or deployment were introduced.

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

### Verification boundary of the earlier design checkpoint

- This work changes requirements and executable design/tests, not social runtime,
  provider adapters, database migrations or deployment.
- No Codex task, live provider operation or image generation ran. Native queues,
  actual MCP incremental delivery, MAX Web, imagegen, runtime permissions,
  database concurrency and infrastructure-independence canaries remain unrun.
- Existing Google limiter findings are documented, not fixed by this batch.
- Schema-valid forbidden calls carry runtime-oracle requirements; schema tests
  do not claim that an absent runtime enforced those permission/timing rules.
