# Documentation

This directory is feature-oriented. Each feature should have one canonical home in `docs/features/`.

## Quick Routing

- Machine-readable map: `docs/routes.yml`
- Feature index: `docs/features/README.md`
- Requirements governance: `docs/operations/requirements-governance.md`
- LLM gateway and limits: `docs/features/llm-gateway/README.md`

## Canonical Sections

- Architecture: `docs/architecture/`
- Operations: `docs/operations/`
- Features: `docs/features/`
- LLM and prompts: `docs/llm/`
- References and templates: `docs/reference/`
- Backlog: `docs/backlog/`
- Reports and incidents: `docs/reports/`
- Tools: `docs/tools/`

## Adding Or Updating Docs

1. New feature: add `docs/features/<feature>/README.md`.
2. Add or update the feature entry in `docs/routes.yml`.
3. Do not create a duplicate document if an existing canonical doc can be extended.
4. Keep status markers explicit: `Draft`, `Fixed`, `Not done`, `Not confirmed by user`, `Done`.
5. Behavior/code changes must update docs and `CHANGELOG.md`.

