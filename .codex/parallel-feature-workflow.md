# Parallel Feature Workflow

This repository carries a portable Codex `feature-fanout` layer for complex multi-point work.

## Automatic trigger

Users do not need to type `$feature-fanout`, "use subagents", "use worktrees", or any process instruction.

- 3+ numbered/bulleted code/product requirements → start with a Fanout Decision.
- 5+ requirements or cross-area work → create an execution matrix, dependency graph, and lane map before editing.
- 5+ requirements or independent areas → use/read-only subagents when available and decide whether writable lanes need branch/worktree isolation.
- If subagents/worktrees are not used, say why explicitly.

## Required artifacts for full fanout

- execution matrix
- dependency graph
- lane map
- worker RESULTS.md per writable lane
- integration report
- final requirement closure table

## Safe defaults

- parallel read-only exploration is encouraged
- parallel writes require branch/worktree isolation
- final integration is serial
- every lane must be committed, rejected, blocked with patch artifact, merged, or superseded
- dirty current worktrees must be preserved, not used as an excuse to stop

## Branch naming

- worker: `agent/<feature>/<lane-id>`
- integration: `integration/<feature>`
- setup: `chore/codex-fanout-defaults`

## Completion

A run is not complete until every original requirement has a final status and the worktree audit shows no abandoned dirty worker worktree.
