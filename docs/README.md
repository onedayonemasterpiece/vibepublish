# Documentation

## Active owner-authorized rollout — 2026-09-05

[Codex on DevCoveer: implementation, real Imagegen and product acceptance](handoffs/codex-full-product-rollout-20260905.md)
is the current execution task. The owner rejected the reduced Telegram/VK-only
proposal. Real generate/tune/compose, candidates and selection, inline publishing,
image/emoji readback and deployment are required. Previous ChatGPT-stage limits
on delegation/generation/deployment are historical for this task; actual security,
access, budget and destination permissions remain in force. Saving this task does
not mean code delivery, host activation or acceptance has already succeeded.

**PR #1 still has a source-delivery gap.** Begin with
[current runtime delivery and evidence](operations/social-runtime.md). The core,
emoji palette/selector, VisualService, contract/skill 1.5 and all archived tests
are transferred. The rich-text compiler and VK adapter are delivered; at the
pre-handoff checkpoint `adapters/codex_imagegen.py` is absent after a recorded
request-safety response. Historical full-source test counts are not remote CI.
The new task does not ask another agent to proxy that denied payload.

## Current implementation

- [Social operations](features/social-operations/README.md),
  [MCP contract](features/social-operations/mcp-contract-v1.md) and
  [canonical skill](llm/vibepublish-social-skill.md): eight tools, native queues,
  scoped access, immutable revisions, progress and provider readback.
- [Telegram custom emoji](features/social-operations/telegram-custom-emoji-v1.md):
  sets, private numbered media, singles/chains, aliases/rules and frozen entities.
- [Shared visuals](features/social-visuals/README.md) and
  [DevCoveer image executor](operations/devcoveer-imagegen.md): local Codex **on
  DevCoveer**, not the owner's desktop. See the
  [ordinary task route](operations/codex-task-imagegen.md) and
  [current stand acceptance](operations/devcoveer-acceptance-20260905.md) for
  actual activation, verified effects and remaining gaps.
- [Native adapter provenance](reference/native-adapter-provenance.md),
  [acceptance matrix](features/social-operations/acceptance-tests-v1.md) and
  [dependency/SDK verification](operations/dependency-sdk-verification.md).

MAX remains separately owned in PR #2. Do not relaunch or duplicate its task or
use its branch to deliver a denied core payload. Read that PR's current HEAD and
comments rather than copying old locator/fixture status from a handoff.

## Historical handoffs

[Implementation start](handoffs/implementation-start-20260904.md),
[native/visual delivery](handoffs/native-visual-delivery-20260905.md) and
[emoji/SDK delivery](handoffs/emoji-imagegen-delivery-20260905.md) preserve earlier
checkpoints. Their old remote HEADs, execution limits and environment blockers
are not the current task. The [former ChatGPT continuation](handoffs/core-emoji-imagegen-continuation-20260905.md)
now points to the full Codex rollout. The [separate MAX handoff](handoffs/max-web-codex-20260905.md)
is historical coordination for the existing task, not permission to launch another.

The owner corrections of September 4 remain binding: native-only schedules,
partner reads within active publishing destinations, early per-child progress,
forward attribution and personal routing profiles. Neither the old audit's local
scheduler nor its separate partner-read grant supersedes those corrections.

## Routing and maintenance

Machine-readable map: [routes.yml](routes.yml). Feature index:
[features/README.md](features/README.md). Governance:
[requirements](operations/requirements-governance.md) and
[repository workflow](operations/repository-workflow.md).

Use an existing canonical feature home. Architecture lives in `architecture/`,
operations in `operations/`, model instructions in `llm/`, references in
`reference/`, backlog in `backlog/`, reports/incidents in `reports/`, handoffs in
`handoffs/` and tools in `tools/`. Keep explicit Draft, Fixed, Not done,
Not confirmed by user and Done boundaries. A schema pass, accepted tree or local
archive is not proof of a remotely delivered and verified runtime.
