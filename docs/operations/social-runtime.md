# VibePublish runtime and delivery status — 2026-09-05

Status: **Not confirmed by user / partial acceptance**. Keep release/full CI unaccepted.

## Current isolated acceptance

The [canonical DevCoveer report](devcoveer-acceptance-20260905.md) records the
new adapter, dedicated Telegram worker, actual native lifecycle/readback, public
MCP, 375 passing local tests and remaining VK/imagegen/ingress durability gaps.
This acceptance branch supersedes missing-module and no-live-call statements
below; those describe the earlier remote core delivery only. Main/MAX unchanged.

## Historical remote-core delivery (not current acceptance state)

## Current source

Branch: `work/vibepublish-core-20260904`.
Source commit: **`ae73b259ddf60c80875c285d3e5c9d51723ce3f0`**.
Tree: **`804d922019fc4ec417f982ace70ef3342f8d2eb8`**.
This adds `social_operations/rich_text.py` and `adapters/vk.py` to `b84c2082`.
Both complete files were accepted by the normal GitHub tree action and copied
without modification from the verified archive. Commit/ref readback succeeded;
independent local reconstruction matches the exact accepted tree. Existing core,
contracts, tests, dependency pins and mandatory CI were not rewritten.

**132 of the archive's 133 source paths are present.** The only missing file is
`adapters/codex_imagegen.py`. Its full-file write in this continuation returned:

> Этот вызов инструмента был заблокирован OpenAI, поскольку мы не смогли определить статус безопасности запроса.

No new tree was returned for that request. It was not retried via another route,
encoding, partial file, CI, MAX or an agent. Successful Telegram/VK writes do not
imply that the Codex module was delivered. Older three-module and 48-path counts
are superseded by this section. Prior source history is preserved in Git.

## Checks on the delivered source

A new empty Python 3.13.5 virtualenv installed all 70 locked dependency wheels
using `--no-index --only-binary=:all: --require-hashes`; `pip check` passed before
and after application installation without dependency resolution. No system-site
Python packages were reused. OS Cairo/fonts/Chromium are available, not a fresh
OS-image claim. The local checkout deliberately does not contain the undelivered
Codex module during these checks.

- Core-aware SDK gate: **PASS**, real Telethon 1.44.0; all 14 request constructors
  roundtrip through the actual compiler, including three custom entities. No RPC.
- Strict full test collection: **296 collected, one import error** in
  `tests/visuals/test_codex_imagegen.py`; missing `adapters.codex_imagegen`.
- Diagnostic full invocation with `--continue-on-collection-errors`:
  **296 passed, one collection error, 199 subtests passed**, 23.93 seconds,
  exit **1**. This includes Telegram emoji/native SDK, VK, MCP/HTTP/worker,
  browser preview and shared visual tests. It is explicitly NOT a green full
  suite: 31 archived Codex-process tests cannot collect without their module.
- Hosted CI for the source commit: run **33964190704**. Read its actual final
  result in PR #1; a pending run or the diagnostic count above is not a PASS.

The workflow and tests remain unchanged; no import skips, stubs or exclusions
were introduced. The old 327 + 199 full result belongs to the complete archived
source and is not claimed for this partial remote checkout.

## Preserved requirements and remaining acceptance

One SQLite/WAL/FULL application serves HTTP and MCP, with eight tools,
contract/skill 1.5 and migration 3. Core owns current authorization, immutable
requests/plans, idempotency, per-connection locks, durable dispatch/fencing,
private assets and per-child progress. Native schedules are submitted to the
provider immediately, never held by a local publication timer. Uncertain effects
are observed without resubmission; partial provider successes are preserved.

Partner reads cover provider-visible content and queues only in active publishing
bindings, not another principal's drafts/assets. Exact item CAS and ordered
provider-media bindings do not assert equality of transcoded bytes. The Telegram
compiler now accompanies the existing catalogs, numbered visual picker,
ordered/repeated emoji chains, immutable aliases/rules and semantic readback.
[Emoji requirements](../features/social-operations/telegram-custom-emoji-v1.md)
remain binding; their earlier delivery banner is superseded by this status.

[VisualService](../features/social-visuals/README.md), importer and compositor
retain immutable budgets, exact editorial copy, private lineage and one parent
continuation. Standalone selection does not publish; preview needs approval;
synthetic images cannot enter native publication. Actual image-only Codex
CLI/skill/controls **on DevCoveer**, real artifacts and cost limits remain
unverified separately from the missing source file. No guessed OpenCode,
personal-PC, Google or API-key fallback is substituted.

No live provider/model call, session use, deployment, merge or MAX write occurred.
MAX was fresh-read at `9d3e9c37ea2111eaeee30e9ae386d6225438aa3a`; its independent
live test is unresolved and is not accepted or repeated here. Public OAuth/TLS,
onboarding, asset URL/ticket ingress, recovery UI, retention/history pagination,
owner discovery/live analytics, video/stories, full rich/mention coverage and
unproved native capabilities remain the existing release gates.

## Source preservation and next step

Complete reference archive: `vibepublish-sdk-locked-20260905.zip`, 1,474,253 bytes,
SHA-256 `179b101877e10c8d37606a4156a4de35e19cda6f127a26181553537623a5c40c`.
All 203 payload hashes and 133 source hashes were checked. Do not overwrite newer
branch docs with the archive or label its local commit as remotely delivered.

The remaining delivery step is the existing `adapters/codex_imagegen.py`, not a
rewrite of Telegram/VK or a new MAX task. Keep the current request-safety outcome
and [delivery proof rule](repository-workflow.md#proof-of-github-delivery).
Full remote CI, actual DevCoveer host evidence and authorized live/owner acceptance
remain separate requirements.
