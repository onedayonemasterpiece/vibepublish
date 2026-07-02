# Agent Instructions

Purpose: keep `vibepublish` work requirement-led, easy to route, and safe to extend.

## Start Here

1. Open `docs/README.md`.
2. Use `docs/routes.yml` as the machine-readable routing map.
3. Before implementing, open the relevant canonical requirement or feature document.
4. If no canonical document exists for the requested feature, create `docs/features/<feature>/README.md` first and mark requirements as `Draft` or `Not confirmed by user`.

## Model And Consultation Policy

- `Opus`, `Опус`, `Claude Opus`, and `Claude Opus latest` mean Claude with the `opus` model alias.
- If the user asks to use Opus, run Claude as `claude --model opus --effort high` or the project-equivalent command.
- Use Opus for substantial UI/UX, architecture, prompt, and hard debugging consultation.
- Gemini CLI may be used for routine consultation when available. Prefer `gemini -m gemini-3-pro-preview -p "<prompt>" --output-format text`.
- Do not downgrade Gemini to 2.5 or Flash unless the user explicitly approves.
- Keep external-model prompts compact and summarize repository context instead of pasting large raw files.

## Requirements Governance

- Requirements are source-of-truth documents, not after-the-fact notes.
- Before changing behavior, verify that the request does not contradict the current fixed requirements.
- Requirement readiness/status markers must be explicit:
  - `Draft`
  - `Fixed`
  - `Not done`
  - `Not confirmed by user`
  - `Done`
- Do not mark an item `Done` based only on internal validation. Internal validation may justify `Not confirmed by user`; explicit user confirmation is required for `Done`.
- When the user asks to update, clarify, or confirm requirements, first classify the current document into:
  - `Already present`
  - `Needs clarification`
  - `Missing`
- Requirement-change proposals must cite the current canonical clauses and present a real delta.
- If implementation conflicts with fixed requirements, stop and propose exact requirement-document edits first.
- After a user reports a defect, mark the affected requirement item `Not done` or `Not confirmed by user` before fixing it.

## Documentation Layout

- Feature docs: `docs/features/<feature>/README.md`
- Operations: `docs/operations/`
- Architecture: `docs/architecture/`
- LLM/prompt work: `docs/llm/`
- References/templates: `docs/reference/`
- Backlog: `docs/backlog/`
- Reports/incidents: `docs/reports/`
- Tools: `docs/tools/`
- One fact belongs in one canonical place. Old paths should be short redirect stubs only.

## Change Completion Rules

- Any code or behavior change must update the canonical documentation in `docs/`.
- Any durable code or behavior change must add a short entry to `CHANGELOG.md` under `[Unreleased]`.
- A task is not complete if code changed but docs or changelog are stale.
- Temporary outputs, logs, dumps, screenshots, and run reports go to `artifacts/`; do not commit them.

## Feature Workflow

1. Route: find or create the canonical feature doc.
2. Requirements: confirm current fixed requirements and status markers.
3. Implement: keep edits scoped to the feature and local patterns.
4. Verify: run focused tests and any required operational checks.
5. Record: update docs, routes if needed, and `CHANGELOG.md`.

## UI / Website Work

- For any frontend, layout, visual, UX, landing-page, or design work, use the strongest available UI/UX skill or consultation path before closing.
- If work affects discoverability, page structure, metadata, internal linking, or search performance, also account for SEO and AI-search/GEO visibility.
- Do not mark visual work complete until desktop and mobile renderings have been checked with Playwright CLI or an equivalent rendered verification workflow.
- The verification must inspect the actual rendered result, not only code or CSS.

## LLM Gateway And Limit Control

- Use `google_ai.GoogleAIClient` for Google AI / Gemini / Gemma calls.
- Do not add direct provider SDK calls unless the canonical `docs/features/llm-gateway/README.md` explains why the shared limiter is not applicable.
- Apply the SQL migrations in `migrations/` before expecting cross-process Supabase-backed limits.
- Secrets live in environment variables or approved secret stores, never in code, docs, tests, or committed artifacts.
- The default limiter policy is fail-fast: callers handle deferral/retry instead of sleeping inside the gateway.

## Incidents

- User-visible production degradation, missed scheduled work, or an `INC-*` mention triggers incident workflow.
- Create a record from `docs/reports/incidents/TEMPLATE.md` if one does not exist.
- Treat incident records as regression contracts until fixed and verified.

## Git Policy

- Review `git status` before staging, committing, pushing, or deploying.
- Stage files explicitly; do not sweep unrelated changes into commits.
- Never commit secrets, local env files, cache files, build output, or `artifacts/`.
- Keep durable project changes reasonably synced to the remote once the repository has an origin.

<!-- codex-feature-fanout:start -->
## Automatic complex multi-point work

The user is not expected to type `$feature-fanout`, "use subagents", "use worktrees", or any special process instruction. Detect the workflow from the shape of the task.

This instruction counts as an explicit request to use Codex subagents, worker lanes, branches, and worktrees when the trigger conditions below are met.

### Trigger levels

Use these trigger levels:

1. `fanout-decision`
   Trigger when the user gives:
   - any numbered/bulleted list with 3+ distinct code/product requirements;
   - several unrelated fixes;
   - a broad task that may touch multiple files.

   Required behavior:
   - start with a short Fanout Decision;
   - preserve every requirement as a stable ID;
   - state whether full fanout is needed.

2. `fanout-required`
   Trigger when the user gives:
   - 5+ distinct requirements;
   - a feature touching multiple areas such as UI/API/tests/config/data/schema;
   - work where requirements may be lost if implemented linearly;
   - a request mentioning many fixes/dorabotki/доработки;
   - a task likely to need parallel discovery/review.

   Required behavior before editing:
   - create an execution matrix;
   - create a dependency graph;
   - create a lane map;
   - decide which lanes are read-only parallel, writable worktree workers, serial integrator work, and final reviewer work.

3. `subagent-required`
   Trigger when:
   - `fanout-required` is true and there are independent discovery/review areas;
   - there are 5+ requirements;
   - there are independent UI/backend/test/documentation areas;
   - a long task risks context pollution or dropped requirements.

   Required behavior:
   - use read-only subagents for exploration/review when available;
   - use writable worker agents only through branch/worktree isolation;
   - if subagents are unavailable or not used, explicitly say why and still use the execution matrix/lane map/checklist discipline.

### Required first response shape when triggered

For triggered tasks, begin with:

```text
Fanout Decision: enabled | not needed
Trigger: <why>
Requirements preserved: R01...Rxx
Execution mode: read-only parallel | serial | mixed | worktree workers
Subagents/worktrees: planned | not needed because <reason> | unavailable because <reason>
```

For simple one-file atomic tasks, do not over-orchestrate, but if the user gave 3+ numbered/bulleted requirements, still provide a Fanout Decision.

### Child agent effort policy

Do not blindly give child agents the same reasoning effort as the parent session. Choose effort per lane:

- `medium`: narrow read-only mapping, file discovery, simple status checks, mechanical inventory.
- `high`: normal bounded implementation lanes, targeted tests, ordinary review, straightforward integration.
- `extra-high` / maximum available effort: complex architecture, cross-cutting integration, conflict resolution, security/auth/schema/migration changes, incident/regression closure, LLM prompt-quality work, or any lane where a wrong answer could lose requirements or corrupt user work.

If the current Codex surface only exposes `medium`/`high`, use `high` as the maximum available effort and explicitly note when a lane would merit extra-high/max in a richer runner. The orchestrator must record the chosen effort in the lane map for every planned subagent/worker/reviewer lane.

### Non-negotiable lane discipline

- Preserve every original requirement ID.
- Do not implement large multi-point work linearly in one long pass.
- Parallelize discovery aggressively.
- Parallelize writes only through disjoint ownership or separate branch/worktree lanes.
- One writable worker lane = one branch + one worktree + one owner.
- Final integration is serial and owned by one integrator.
- Every worker lane must end as committed, merged, rejected, blocked-with-patch, or superseded.
- No lane may disappear from the final report.
- No worker may leave abandoned dirty worktrees.
- Dirty current worktree is not an excuse to do nothing. Preserve it, avoid dirty files, and continue in isolated worktrees when safe.
- Final response must include Done / Partial / Missing / Blocked / Superseded for every original requirement.
<!-- codex-feature-fanout:end -->
