# VibePublish

Independent Telegram, VK and MAX Web operations service, with one MCP/HTTP application core and an image/video pipeline.

## Current contract: 1.5.0-runtime; offline core, native adapters, emoji and visuals

Owner corrections of 2026-09-04 are Fixed:

- Scheduled posts go into the provider's native queue now. **No VibePublish publication scheduler or local fallback.** Read, preview, edit, reschedule and cancel the actual provider item.
- Return accepted state promptly and expose durable per-provider/per-stage progress without waiting for every provider.
- A partner can read all posts and all scheduled items in each actively bound publishing channel, regardless of author. No separate read grant; no unrelated channel/dialog access. The owner can read whatever the provider account permits.
- Keep indexed publication history, remote identities and dated statistics in the database for fast retrieval. History is not a scheduler or a replacement for live queue reads.

## Start here

- [Canonical requirements](docs/features/social-operations/README.md)
- [Implementation architecture and acceptance gates](docs/features/social-operations/implementation-design-v1.md)
- [Exact MCP grammar, progress and history](docs/features/social-operations/mcp-contract-v1.md)
- [Versioned agent skill](docs/llm/vibepublish-social-skill.md)
- [Imagegen visuals](docs/features/social-visuals/README.md) and [video stories](docs/features/video-stories/README.md)

The [original audit](docs/reports/vibepublish-audit-20260904.md) and historical handoff remain evidence of the earlier checkpoint. Their local-scheduler and separate partner read-grant decisions were rejected by the owner and are superseded by the current requirements. Existing Google limiter audit findings remain open; ordinary publishing does not depend on optional Google rewriting.

## Executable core snapshot

See [runtime setup, tests and limitations](docs/operations/social-runtime.md).
The snapshot contains a real MCP/HTTP service, a separate immediate-command
worker, SQLite/WAL state, private image ingestion and explicit fake providers.
It is **not a deployed publishing service** and has no automatic live connection.
Concrete Telegram/VK adapters are exercised through scripted native transports.
Telegram custom emoji has private numbered media catalogs, revision-bound single/
chain choice, reusable aliases/rules, pre-send native entities and semantic
readback. See [emoji workflow](docs/features/social-operations/telegram-custom-emoji-v1.md).
The existing VisualService now has an optional
[local Codex process executor for DevCoveer](docs/operations/devcoveer-imagegen.md),
tested with an explicitly scripted CLI. It is disabled by default: the installed
host's CLI/skill and image-only controls still require verification. No real
image generation, social canary or deployment was performed. MAX is already a
separate PR #2; no second driver was created.

**The remote checkout is still incomplete, not a runnable release.** Source,
tests, skill and contract have been transferred, but `adapters/vk.py`,
`social_operations/rich_text.py` and `adapters/codex_imagegen.py` received explicit
request-safety blocks and are absent. The installation/test commands below are
acceptance gates, not evidence that this partial checkout passes. The full
implementation remains preserved in the verified source archive; do not rebuild
it from the incomplete tree. [Runtime status](docs/operations/social-runtime.md)
separates current remote delivery from historical full-source results.

```bash
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest tests
```

The canonical contract remains eight tools, sixteen input/output schemas,
125 golden jobs and 44 invalid calls. Offline runtime tests are separate from
these design fixtures and do not establish live provider/browser/model behavior.

## Reproduce design checks

```bash
python -m pip install -r contracts/requirements.txt
python tests/contracts/test_social_mcp_design.py
python contracts/social_mcp_v1.py > social-mcp.v1.generated.json
python contracts/task_corpus_v1.py > task-corpus.v1.generated.json
```

Generated JSON is an output, not another source of truth. No provider credentials are required. See AGENTS.md and docs/routes.yml for governance/routing.
