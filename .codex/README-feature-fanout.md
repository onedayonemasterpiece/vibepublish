# Codex Feature Fanout Portable Layer

This repository includes a portable Codex setup for complex multi-point work.

## What travels with the repo

- `AGENTS.md` managed block with automatic fanout triggers.
- `.agents/skills/feature-fanout/SKILL.md`.
- `.codex/agents/` mapper/worker/reviewer/integrator agents.
- `.codex/config.toml` agent fanout limits.
- `.codex/rules/parallel-workflow-safety.rules` safety prompts/blocks.
- `.codex/scripts/` helper scripts and user-global installer.
- `.codex/parallel-feature-workflow.md` workflow reference.

## Trigger thresholds

- 3+ numbered/bulleted requirements: Fanout Decision required.
- 5+ requirements or cross-area work: execution matrix + lane map required.
- 5+ requirements or independent areas: subagent/worktree decision required.

## Moving to another server

After cloning, repo-level `AGENTS.md` and `.agents/skills` carry the project behavior. If you also want user-global defaults on the new server, run:

```bash
.codex/scripts/install-user-fanout-from-repo.sh
```

The installer is local-only, idempotent, and creates timestamped backups under `~/.codex/backups/`.
