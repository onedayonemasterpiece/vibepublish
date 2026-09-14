# Changelog

## [Unreleased]

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
