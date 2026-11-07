# Documentation

## Story Carousel private MVP and visual references — 2026-11-07

Start with the [canonical feature and current limits](features/story-carousel/README.md).
The owner authorized implementation and a growing bank of actual Slack examples on
November 7. Source now implements one private `vibepublish_carousel` tool with five
commands: create, get, revise, render and export. It stores SVG revisions in the
existing ledger, returns a strip or an original-resolution region, and exports
ordered private media for an exact revision. Generation remains **dot's own tool**.

The private bank has 23 source records and 22 unique images. The repository keeps
[reference metadata](reference/story-carousel/reference-catalog.json); runtime image
reads require the exact bound owner and `visual` scope. The model opens an actual
reference, identifies one useful improvement, revises its SVG and checks the changed
region when that comparison helps. The atlas never substitutes for an original image.

The auditor's [November 7 coordination update](https://mira-projects.slack.com/archives/C0CFP01K292/p1794034087770269)
records the owner's revised display test: seven probe cards in the postponed VK
posts of «Полюбить Калининград», up to ten days ahead, with one
`primary_attachments_mode=carousel` attempt. Telegram and separate test destinations
are no longer prerequisites. Dot's existing private import → render → export E2E is unchanged.

Supporting material:

- [Original research and tutorials](reports/story-carousel-research-2026-11-06.md).
- [Original Opus critique](reports/story-carousel-critique-2026-11-06.md), preserved as authored proposals.
- [36-requirement coverage audit](reference/story-carousel/coverage-audit-2026-11-06.md)
  and [source register](reference/story-carousel/source-register.md).
- [Visual language and E01–E23 audit](reference/story-carousel/visual-language.md),
  [eight narrow illustrations of two principles, excluded from tool examples](reference/story-carousel/blockout-atlas.svg),
  [twelve palettes and Cyrillic directions](reference/story-carousel/palette-catalog.md),
  [composition/review bank](reference/story-carousel/composition-and-review.md) and
  [5+5 variation study](reference/story-carousel/variation-study.md).
- [Platform, media and PastVu verification](reference/story-carousel/platform-media-audit-2026-11-06.md).

Status: implementation authorized (**Fixed**), source implemented,
**Not confirmed by user**. Public runtime deployment and native platform/dot E2E:
**Not done**. Focused source checks and private server image provisioning are evidence
for those specific steps, not production or visual acceptance. The earlier
[full-channel audit and Opus reconciliation](reports/story-carousel-reconciliation-2026-11-06.md)
remain historical research; the canonical feature defines the reduced current contract.

## Active MAX completion correction — 2026-09-08

The owner's [active MAX product-completion task](https://github.com/onedayonemasterpiece/vibepublish/blob/work/vibepublish-max-web-20260904/docs/handoffs/max-product-completion-codex-20260908.md)
authorizes independent necessary core changes in existing PR #1 and MAX changes
in PR #2. Earlier separate-ownership and historical denied-payload notes do not
prohibit independently implementing this task. The additive original-terminal
recovery contract is [canonical here](features/social-operations/mcp-contract-v1.md#original-terminal-recovery-owner-max-completion-correction-2026-09-08).
No historical rejected payload is imported or reconstructed. Code/automated
checks do not establish MAX live acceptance or authorize unrelated deployment.

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

## ChatGPT connection continuation

[OAuth and current connection readiness](operations/chatgpt-readiness-20260906.md)
supersedes stale domain/TLS blockers in the previous acceptance snapshot.

## Current implementation

- [Social operations](features/social-operations/README.md),
  [MCP contract](features/social-operations/mcp-contract-v1.md) and
  [canonical skill](llm/vibepublish-social-skill.md): publication tools plus the
  owner-only Telegram media database, native queues,
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

