---
name: feature-fanout
description: Automatically use for any numbered or bulleted list with 3+ code/product requirements, and require full fanout for 5+ requirements, broad cross-area work, many unrelated edits, or tasks that need subagents, branches, worktrees, lane ownership, integration gates, and final closure audit. The user does not need to invoke this skill explicitly.
---

# Feature Fanout

## Auto-trigger contract

The user does not need to mention this skill.

This skill must be used automatically when:

- the task has 3+ numbered/bulleted requirements, at least for Fanout Decision;
- the task has 5+ requirements, for full execution matrix and lane map;
- the task is broad/cross-area;
- the task risks dropped requirements or context pollution.

When this skill triggers, the first response must visibly include:

- Fanout Decision
- Trigger
- Requirement IDs
- Execution mode
- Subagents/worktrees planned or reason not used

This skill instruction counts as an explicit request to use Codex subagents, worker lanes, branches, and worktrees when trigger conditions are met.


Use automatically when the task is complex or multi-point.


## Child agent effort policy

Do not blindly give child agents the same reasoning effort as the parent session. Choose effort per lane:

- `medium`: narrow read-only mapping, file discovery, simple status checks, mechanical inventory.
- `high`: normal bounded implementation lanes, targeted tests, ordinary review, straightforward integration.
- `extra-high` / maximum available effort: complex architecture, cross-cutting integration, conflict resolution, security/auth/schema/migration changes, incident/regression closure, LLM prompt-quality work, or any lane where a wrong answer could lose requirements or corrupt user work.

If the current Codex surface only exposes `medium`/`high`, use `high` as the maximum available effort and explicitly note when a lane would merit extra-high/max in a richer runner. The orchestrator must record the chosen effort in the lane map for every planned subagent/worker/reviewer lane.


Core invariant:

- Preserve every original requirement ID.
- Do not implement a large multi-point request linearly in one long pass.
- Parallelize discovery aggressively.
- Parallelize writes only through disjoint ownership or separate branch/worktree lanes.
- Serialize final integration.
- No lane is complete until its work is committed, rejected with evidence, blocked with patch artifact, merged, or superseded.
- A dirty main/current worktree is never an excuse to do nothing.

## Phase A — Normalize requirements

Create an execution matrix:

| ID | Requirement | Area | Likely files | Dependencies | Conflict risk | Lane | Parallelizable? | Done when |
|---|---|---|---|---|---|---|---|---|

Rules:

1. Preserve original numbering and wording.
2. If the user did not number the list, assign stable IDs R01, R02, R03.
3. Do not merge requirements silently.
4. Do not drop ambiguous requirements; mark them `needs-interpretation` and choose the safest implementation assumption.
5. Build a dependency graph before write lanes start.

## Phase B — Classify execution mode

Use:

- `read_only_parallel`
- `worktree_worker`
- `serial_integrator`
- `reviewer`
- `blocked_with_handoff`

Parallel write lanes are allowed only when:

- writable scopes are disjoint, or each lane has its own branch/worktree;
- the integrator owns final merge.

Parallel write lanes are forbidden when:

- lanes edit the same file/component without a clear owner;
- lanes change shared schema, auth, routing, migrations, generated code, global state, or core architecture;
- downstream work depends on unstable uncommitted upstream work.

## Phase C — Lane map

Before spawning workers, write:

```yaml
mode:
repo:
base_ref:
base_branch:
integration_branch:
global_constraints:
verification_owner:
stop_conditions:
lanes:
  - id:
    role: planner | worker | reviewer | merge_reviewer
    requirement_ids:
    target:
    depends_on:
    execution_mode: parallel | serial_after_dependency | read_only_until_dependency
    branch:
    worktree:
    writable_files:
    forbidden_files:
    expected_output:
    verification_scope: inspection_only | targeted | full_local | ci_only
    status: planned | spawned | committed | merged | rejected | blocked | superseded
```

Rules:

- Every requirement ID must appear in exactly one primary lane.
- Every writable lane must have an owner.
- Every writable lane must have branch and worktree before implementation starts.
- The orchestrator must not edit inside worker-owned dirty worktrees.
- If native subagents are unavailable, create the lane map and prompt pack; do not pretend subagents were launched.

## Phase D — Branch and worktree discipline

For every writable worker lane:

Branch:

```text
agent/<feature-slug>/<lane-id>
```

Worktree:

Use an ignored/out-of-repo worktree root, preferably:

- existing ignored `.worktrees/`;
- existing ignored `worktrees/`;
- otherwise adjacent/out-of-repo or `~/.codex/worktrees/<repo-slug>/<lane-id>`.

Baseline gate:

- capture `git status --short --branch`;
- record `git rev-parse HEAD`;
- if worker worktree is dirty before work begins, recreate it or block the lane.

Scope:

- edit only writable files;
- do not touch forbidden files;
- do not run destructive git commands;
- do not push unless explicitly asked.

Handoff:

The worker must produce committed changes or a named patch artifact.

Required file:

```text
.codex/lanes/<lane-id>/RESULTS.md
```

Required content:

```markdown
# Lane <lane-id> Results

## Status
committed | blocked-with-patch | rejected-by-worker

## Requirement IDs
- Rxx

## Branch
agent/<feature>/<lane-id>

## Worktree

## Base SHA

## Head SHA

## Files changed

## Commands run

## Tests / verification

## Risks

## Merge notes
```

Completion invariant:

- A worker lane is not complete if `git status --short` shows uncommitted changes, unless it produced a named patch artifact and is marked `blocked-with-patch`.

## Phase E — Integration

The integrator owns final code consistency.

Integration branch:

```text
integration/<feature-slug>
```

Before accepting each lane:

- confirm clean integration worktree;
- inspect lane `RESULTS.md`;
- inspect `git diff base..lane_head`;
- reject unrelated changes.

Merge strategy:

- prefer cherry-picking small worker commits;
- use normal merge only when useful;
- never use bare `git push --force`;
- if force push is explicitly required later, use `--force-with-lease`.

Conflict policy:

- resolve conflicts only in integration worktree;
- do not edit worker-owned dirty worktrees;
- if conflict cannot be safely resolved, create `.codex/integration/<lane-id>-conflict.md` and mark blocked.

No lost work:

- Every lane must end as merged, rejected, blocked-with-patch, or superseded.

Integration report:

```text
.codex/integration/INTEGRATION_REPORT.md
```

Include:

| Lane | Requirement IDs | Branch | Status | Head SHA | Merge/cherry-pick | Evidence |
|---|---|---|---|---|---|---|

## Phase F — Final closure audit

Before final response:

| ID | Requirement | Status | Evidence | Missing/Risk |
|---|---|---|---|---|

Allowed statuses:

- Done
- Partial
- Missing
- Blocked
- Superseded

Do not claim completion unless every requirement is Done or explicitly explained.
Do not hide skipped tests.
Do not hide unmerged worker changes.
Do not abandon dirty worker worktrees.
