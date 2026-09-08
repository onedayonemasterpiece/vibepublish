# Documentation

## Current work entrypoints — 2026-09-08

- **[Active MAX product-completion task for Codex](handoffs/max-product-completion-codex-20260908.md)** — current owner instruction for completing MAX end to end, including necessary shared core work.
- [MAX Web active runbook](operations/max-web.md) — current operational baseline and acceptance matrix.
- [Start implementation in a new ChatGPT window](handoffs/implementation-start-20260904.md).
- [Current forwarding, primary-channel profiles and skill extension](features/social-operations/forwarding-and-editorial-profiles-v1.md), contract `1.2.0-design`.
- [Automated acceptance tests and evidence boundaries](features/social-operations/acceptance-tests-v1.md).

Historical MAX handoffs from 2026-09-05/07 are redirect stubs only. Their old executor-ownership rules, missing-archive assumptions and source-write-refusal language must not override the 2026-09-08 owner instruction.

The social runtime and MCP base design remain in the existing social-operations documents. Read their v1.1 native-only queue/access/progress rules together with the v1.2 extension; they are not alternative architectures. The old audit's local scheduler and default-deny partner channel reads remain superseded.

The executable contract and new test cases are updated to v1.2. The canonical skill text may still require synchronization with the forwarding/profile extension before runtime release; treat that as ordinary implementation work, not as a blocker to MAX completion.

## Quick routing

Machine-readable map: `docs/routes.yml`. Feature index: `docs/features/README.md`. Requirements governance: `docs/operations/requirements-governance.md`. LLM gateway: `docs/features/llm-gateway/README.md`.

This directory is feature-oriented. Each feature has one canonical home in `docs/features/`. Architecture lives in `docs/architecture/`, operational instructions in `docs/operations/`, model instructions in `docs/llm/`, references in `docs/reference/`, backlog in `docs/backlog/`, reports/incidents in `docs/reports/`, handoffs in `docs/handoffs/` and tools in `docs/tools/`.

## Adding or updating docs

Route to an existing canonical feature before adding another document. Add/update the relevant entry in routes.yml. Keep explicit statuses: Draft, Fixed, Not done, Not confirmed by user, Done. Code/behavior changes update documentation and CHANGELOG. A passing schema fixture is not evidence of runtime or live-provider acceptance.
