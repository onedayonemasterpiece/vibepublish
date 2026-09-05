# Documentation

## Current continuation — 2026-09-05

- [Continue core/Telegram emoji/imagegen in ChatGPT](handoffs/core-emoji-imagegen-continuation-20260905.md).
- [Telegram emoji set, visual choice and sequence workflow](features/social-operations/telegram-custom-emoji-v1.md): owner intent Fixed, detailed design Draft, runtime Not done.
- [MAX task](handoffs/max-web-codex-20260905.md) is already assigned in PR #2; do not relaunch it. Its synthetic driver still needs the actual attached archive, shared-port integration and observed live selectors.

The complete local core/native/visual code is in the separately delivered ZIP,
not this remote branch. Read [runtime status](operations/social-runtime.md).
Imagegen host is local Codex **on DevCoveer**, not the owner's desktop.

## Historical design entrypoints — 2026-09-04

- [Start implementation in a new ChatGPT window](handoffs/implementation-start-20260904.md).
- [Separate Codex task for the MAX Web adapter](handoffs/max-web-codex-20260904.md).
- [Current forwarding, primary-channel profiles and skill extension](features/social-operations/forwarding-and-editorial-profiles-v1.md), contract `1.2.0-design`.
- [Automated acceptance tests and evidence boundaries](features/social-operations/acceptance-tests-v1.md).

The social runtime and MCP base design remain in the existing social-operations documents. Read their v1.1 native-only queue/access/progress rules together with the v1.2 extension; they are not alternative architectures. The old audit's local scheduler and default-deny partner channel reads remain superseded.

The executable contract and new test cases are updated to v1.2. The write updating the canonical skill text was blocked by the connector in this session; `docs/llm/vibepublish-social-skill.md` remains v1.1. The core implementation batch must synchronize its forwarding/profile sections and examples with v1.2 before exposing the runtime. Requirements for that synchronization are complete in the extension; do not claim the old text already contains them.

## Quick routing

Machine-readable map: `docs/routes.yml`. Feature index: `docs/features/README.md`. Requirements governance: `docs/operations/requirements-governance.md`. LLM gateway: `docs/features/llm-gateway/README.md`.

This directory is feature-oriented. Each feature has one canonical home in `docs/features/`. Architecture lives in `docs/architecture/`, operational instructions in `docs/operations/`, model instructions in `docs/llm/`, references in `docs/reference/`, backlog in `docs/backlog/`, reports/incidents in `docs/reports/`, handoffs in `docs/handoffs/` and tools in `docs/tools/`.

## Adding or updating docs

Route to an existing canonical feature before adding another document. Add/update the relevant entry in routes.yml. Keep explicit statuses: Draft, Fixed, Not done, Not confirmed by user, Done. Code/behavior changes update documentation and CHANGELOG. A passing schema fixture is not evidence of runtime or live-provider acceptance.
