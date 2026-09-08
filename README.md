# VibePublish

Independent Telegram, VK and MAX Web operations service, with one MCP/HTTP application core and an image/video pipeline.

## Current owner requirements

- Scheduled posts use the provider's native queue. **No VibePublish publication scheduler or local fallback.** Read, preview, edit, reschedule and cancel the actual provider item.
- Return accepted state promptly and expose durable per-provider/per-stage progress without waiting for every provider.
- A partner can read all posts and all scheduled items in each actively bound publishing channel, regardless of author. No separate read grant; no unrelated channel/dialog access. The owner can read whatever the provider account permits.
- Keep indexed publication history, remote identities and dated statistics in the database for fast retrieval. History is not a scheduler or a replacement for live queue reads.

## Start here

- **[Active MAX product-completion task for Codex](docs/handoffs/max-product-completion-codex-20260908.md)**
- [MAX Web active runbook](docs/operations/max-web.md)
- [Canonical social-operation requirements](docs/features/social-operations/README.md)
- [Implementation architecture and acceptance gates](docs/features/social-operations/implementation-design-v1.md)
- [Exact MCP grammar, progress and history](docs/features/social-operations/mcp-contract-v1.md)
- [Versioned agent skill](docs/llm/vibepublish-social-skill.md)
- [Imagegen visuals](docs/features/social-visuals/README.md) and [video stories](docs/features/video-stories/README.md)

## MAX execution precedence

For the current MAX work, the 2026-09-08 Codex task and active MAX runbook supersede older MAX/recovery handoffs and historical PR comments as execution instructions.

A source-write/safety refusal recorded in an earlier ChatGPT window for a particular attempted payload does **not** prohibit Codex from independently implementing required MAX or shared core functionality from the current repository. The owner has explicitly authorized the same Codex task to develop both MAX-specific code and necessary shared core changes.

Older handoffs remain available through Git history for provenance only.

## Verification boundary

VibePublish is not accepted as a complete MAX product until real lifecycle cases pass through `MCP → core/application → worker → ProviderAdapter → RealMaxDriver → MAX Web`.

Fixtures, schema tests, screenshot interpretation and green CI are supporting evidence, not a substitute for real publish/read/edit/delete, media, native schedule/reschedule/cancel/output and crash/recovery acceptance in the owner-authorized targets.

MAX must remain a persistent-profile Playwright adapter with provider-native scheduling, not a local timer.

## Reproduce design checks

```bash
python -m pip install -r contracts/requirements.txt
python tests/contracts/test_social_mcp_design.py
python contracts/social_mcp_v1.py > social-mcp.v1.generated.json
python contracts/task_corpus_v1.py > task-corpus.v1.generated.json
```

Generated JSON is an output, not another source of truth. No provider credentials are required for these design checks. See `AGENTS.md` and `docs/routes.yml` for governance/routing.
