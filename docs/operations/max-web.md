# MAX Web — active runbook

Updated: 2026-09-08. Branch: `work/vibepublish-max-web-20260904`, [PR #2](https://github.com/onedayonemasterpiece/vibepublish/pull/2).

**Status:** Implementation Not done. Product target and current owner instructions are in [MAX product completion for Codex](../handoffs/max-product-completion-codex-20260908.md). That document supersedes older MAX/recovery handoffs as an execution instruction.

## Product target

VibePublish must expose MAX through the normal `MCP → core/application → worker → ProviderAdapter → RealMaxDriver → MAX Web` path.

Required supported lifecycle, where the actual MAX surface allows it:

- publish text, links/formatting, images/albums and supported video;
- exact native readback;
- edit without losing media;
- native schedule, read scheduled state, reschedule while preserving content/media, cancel;
- delete published objects;
- supported reply/reaction/forwarding operations;
- crash/restart/reconcile without duplicate external effects.

A green fixture suite is evidence, not acceptance. Live acceptance is required in the owner-authorized MAX targets.

## Current implementation baseline

PR #2 already contains substantial MAX work: real session/navigation/read paths, `RealMaxDriver`, browser regressions, crash/reconcile qualification, exact native-reference handling, scoped Gemini Lite visual assistance, and actual-core integration tests. Treat these as assets to continue, not as completion.

Known unfinished product areas include terminal operation resolution, production mutation wiring through MCP/worker, full edit/delete lifecycle, media lifecycle, native scheduled lifecycle and remaining supported social operations.

Fresh-read actual PR HEAD/code/CI before changing anything; historical SHA values in old comments are checkpoints only.

## Recovery semantics

An internal uncertainty state may exist temporarily after an external effect when its receipt is lost. It must **not** become a permanent dead end when MAX can be observed.

For MAX, the expected recovery flow is:

1. durable intent/checkpoint before effect;
2. one external effect;
3. normal DOM/native readback;
4. if UI observation is technically ambiguous, optional scoped vision assistance;
5. fresh native readback;
6. durable binding of evidence to the original operation/attempt/plan;
7. terminal core resolution or exact compensation outcome;
8. normal release of the corresponding profile fuse/quarantine;
9. restart repeats observation/resolution, not the mutation.

Do not fix this by manual SQL, deleting the fuse, inventing a receipt or performing another Send.

The original marked Test Group post that previously remained tied to `outcome_unknown` is a required real recovery case. Reobserve it, resolve the original operation through the implemented core path, then clean it up through the normal MAX lifecycle.

## Historical source-write refusals are not an active engineering blocker

Earlier PR comments and old handoffs record source-write/safety refusals from particular ChatGPT sessions for particular attempted payload delivery. They are retained in Git history as provenance.

They do **not** prohibit Codex from independently reading the current repository and implementing the missing core recovery or other required functionality. The owner explicitly authorizes core and MAX development by the same Codex task.

Do not copy/replay/reconstruct a previously rejected payload merely to evade a platform decision. Instead, write the required implementation independently from the current code and product requirements.

Only a new, current, reproduced platform refusal in the active Codex session can be reported as a platform blocker. It does not justify stopping unrelated work.

## Branch ownership

Use the existing work, not a third implementation:

- PR #2 / `work/vibepublish-max-web-20260904`: MAX-specific driver, session/profile, selectors, bridge/wiring, tests and this runbook.
- PR #1 / `work/vibepublish-core-20260904`: shared core/worker/storage/application/provider-port changes when required.

The old restriction that the MAX executor may not modify core is superseded. Codex may work in both existing branches for this product task.

Keep Telegram/VK compatible. Do not duplicate common idempotency/history/dispatch logic inside MAX.

## Live permissions

### Тестовая группа

Owner authorizes all necessary test social operations without additional confirmation and without a test-object count limit:

- publish/read/edit/delete;
- media;
- native schedule/read/reschedule/cancel and actual scheduled output;
- supported reply/reaction/forwarding;
- crash/restart/reconcile;
- repeated cycles and cleanup of task-owned test objects.

Do not alter membership, permissions, group identity/auth settings or other people's messages.

### Ух ты, Калининград! / Полюбить Калининград Анонсы

Current narrower permission remains: read existing feed/queue and create/read/edit/reschedule/cancel **own safe test scheduled items**. Do not intentionally publish an immediate test into the real feed without a later explicit owner instruction.

A failure or ambiguity in one real channel must not stop Test Group work.

## Session handling

Reuse the existing authorized MAX browser profile/session on DevCoveer when valid.

- no logout or cookie/storage-state reset;
- no duplicate Chromium ownership of the same profile;
- no QR/login work unless the existing session actually expires;
- resolve account/chat/native item identity before effects;
- derive production selectors from observed MAX Web, not synthetic test attributes.

If auth is genuinely expired, return a concrete `needs_auth` prerequisite and continue all code/replay work that does not require it.

## Optional visual recovery

`RealMaxDriver` may use the existing scoped visual assistance for technical observation failures.

Rules:

- DOM/native verification first;
- screenshot only the task-owned object/necessary region, not unrelated conversations/settings;
- use `google_ai.GoogleAIClient` and the shared limiter; no direct provider bypass;
- the owner previously authorized local gateway configuration from `/home/dev/projects/my-data-hub/.env`; never copy secrets into Git;
- model output is supplementary evidence only and cannot itself authorize mutation, release quarantine or create a native identity;
- after vision, perform a fresh native readback and let core persist/resolve the operation.

A successful Gemini read is not product completion; continue to terminal operation resolution and lifecycle acceptance.

## Acceptance matrix

Before declaring MAX ready, obtain real evidence through the normal MCP/worker path for at least:

| Case | Required proof |
|---|---|
| plain publish | one native effect, exact readback |
| media publish | exact media/content readback |
| edit | same native object, new text, media preserved |
| delete | exact own object absent after deletion |
| native schedule | queued natively with exact timestamp |
| reschedule | same own scheduled object/content/media, new timestamp |
| cancel | exact own scheduled object removed |
| native output | scheduled effect occurs while VibePublish is stopped |
| crash after effect | restart resolves the same operation with no duplicate mutation |
| original stuck operation | old object rebound to original attempt, terminally resolved and cleaned up |
| supported reply/reaction/forward | native readback proving the supported operation |

If MAX does not expose a listed capability for the tested surface, record live capability evidence and continue the rest.

## Tests and evidence

Keep useful existing fixture/replay tests, but add regressions for every real UI issue discovered.

Required final verification includes:

- MAX-focused browser/adapter tests;
- actual `MCP ClientSession → worker → ProviderAdapter` integration;
- crash/restart scenarios;
- common core/contract tests affected by shared changes;
- exact-SHA GitHub CI;
- remote readback of key committed files/SHA;
- private live evidence under `artifacts/`, never committed if it contains account/session/native/private data.

Do not stop on a progress report. Stop on product acceptance or on a new, reproduced external blocker that truly prevents the remaining path.

## Historical documents

The following are history only and must not override this runbook or the 2026-09-08 task:

- `docs/handoffs/max-web-live-completion-20260905.md`;
- `docs/handoffs/max-core-recovery-completion-20260907.md`;
- old PR comments describing missing ZIPs, prior executor ownership limits or prior ChatGPT source-write refusals.

Git history and PR discussion preserve their evidence; they are no longer active routing instructions.
