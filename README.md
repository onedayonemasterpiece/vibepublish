# VibePublish

Independent Telegram, VK and MAX Web operations service, with shared MCP/HTTP application services and an image/video production pipeline.

## Current status

**Implementation-design checkpoint, not a deployed publishing service.** Owner product requirements are `Fixed`; new engineering decisions are `Not confirmed by user`; social runtime implementation is `Not done`.

The repository contains an audited architecture, exact executable MCP schemas, a versioned agent skill, 80 golden task fixtures and 20 negative calls. Eight offline contract test methods passed. This does not prove live provider behavior, weak-agent accuracy, MAX Web reliability or imagegen availability.

The existing `google_ai/` gateway and SQL migrations are legacy scaffold code with concrete audit findings, not a demonstrated tenant-safe quota foundation. Ordinary social publishing must not depend on optional Google adaptation.

## Start here

- [Canonical social requirements and design map](docs/features/social-operations/README.md)
- [Independent audit: problems, evidence and limitations](docs/reports/vibepublish-audit-20260904.md)
- [Implementation architecture and delivery gates](docs/features/social-operations/implementation-design-v1.md)
- [MCP taxonomy, argument contract and offline results](docs/features/social-operations/mcp-contract-v1.md)
- [Image generation/tuning through imagegen](docs/features/social-visuals/README.md)
- [Original video-story generator scope](docs/features/video-stories/README.md)

MAX remains a dedicated persistent-profile Playwright driver; MAX API is not a current dependency. Initial implementation is direct GitHub work. Later DevCoveer integration must prove the actual `$imagegen` route and live provider canaries; no Codex task was used for the current audit.

## Reproduce design checks

```bash
python -m pip install -r contracts/requirements.txt
python tests/contracts/test_social_mcp_design.py
python contracts/social_mcp_v1.py > social-mcp.v1.generated.json
python contracts/task_corpus_v1.py > task-corpus.v1.generated.json
```

The generated JSON files are outputs, not a second source of truth. No credentials, database or provider connection is required for these checks.

See `AGENTS.md`, `docs/README.md` and `docs/routes.yml` for requirements governance and routing. Do not turn successful schema tests into a production-readiness claim.
