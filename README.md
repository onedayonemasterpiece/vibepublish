# VibePublish

Independent Telegram, VK and MAX Web operations service, with one MCP/HTTP application core and an image/video pipeline.

## Current design: 1.1.0-design

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

## Verification boundary

This is an implementation-design checkpoint, **not a deployed publishing service**. Runtime remains Not done. The corrected executable contract has eight tools, sixteen input/output schemas, 105 golden jobs and 30 invalid calls. Fourteen offline test methods passed. These are schema/projection tests, not live provider, latency, weak-model, browser or database tests.

MAX remains a persistent-profile Playwright adapter, with native queue support proved during integration rather than replaced with a local timer. Later DevCoveer checks must prove real imagegen, independent credentials and provider execution after VibePublish is stopped. No Codex task, provider publication or image generation ran during this correction.

## Reproduce design checks

```bash
python -m pip install -r contracts/requirements.txt
python tests/contracts/test_social_mcp_design.py
python contracts/social_mcp_v1.py > social-mcp.v1.generated.json
python contracts/task_corpus_v1.py > task-corpus.v1.generated.json
```

Generated JSON is an output, not another source of truth. No provider credentials are required. See AGENTS.md and docs/routes.yml for governance/routing.
