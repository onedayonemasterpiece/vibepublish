# Changelog

## [Unreleased]

### Added

- Independent 2026-09-04 architecture/product/security audit of VibePublish,
  including 20 design findings and five targeted Google limiter findings.
- Social implementation design: SQLite/outbox ownership, immutable publication
  revisions, scoped access, scheduling/cancellation, provider readback, MAX Web
  state machine, recovery, operational restoration and EventsBot cutover gates.
- Executable eight-tool MCP schema design and auth-filtered projection; 80
  Russian golden task cases, 20 invalid-call cases and eight passing offline
  contract test methods. These do not constitute runtime or weak-agent tests.
- Versioned social skill and exact input/output, error and HTTP projection rules.
- Social visuals contract preserving the required imagegen route, explicit exact
  text fields, candidate selection and consent-controlled provenance.
- Canonical video-story feature preserving Telegram editorial control, Kaggle
  rendering, geo/time filters, music, subtitles, enhancement and approval.
- Initial standalone project scaffold.
- Feature-oriented documentation routing.
- Google AI / Supabase limit-control framework and migrations.
- Original fixed Social Operations requirements and EventsBot donor map.

### Changed

- Reconciled the social canonical README with the later owner corrections;
  superseded the old competing tool taxonomy and clarified external default-deny
  reads, multi-tenant protection from the first core batch and MAX Web-only scope.
- Root README and routes now lead to the audited implementation design, with
  social runtime explicitly Not done and legacy limiter findings visible.

### Not implemented or verified by this checkpoint

- No social runtime, provider adapter, database migration, deployment or Codex
  task was executed. No actual social publication or image generation occurred.
- Existing Google limiter defects were documented, not fixed by this batch.
- MAX Web, real imagegen, independent provider credentials, weak-agent accuracy,
  concurrency and live recovery remain explicit implementation/acceptance gates.
