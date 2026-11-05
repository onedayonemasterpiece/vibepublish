# INC-2026-11-05-max-scheduled-album-cancellation

Status: `Open`
Affected reliability acceptance: `Not done` (initial cancellation remains unexplained). Native scheduling recovered; independent native queue readback verified text, schedule and six ordered media entries, but not per-photo pixel/hash identity.
Scope: documentation-only incident and engineering handoff. No code, configuration, deployment or publication changes are part of this record.

## Summary

MAX native scheduling of a six-photo announcement reached `submitting`, then an account check and the enclosing execute phase were cancelled. The first observed execute ran for 90,151.453 ms and reported `CancelledError`; the adapter recorded `dispatched:false` and `provider_command_failed`.

The service subsequently retried the same attempt. An intermediate running/pending state is not a terminal refusal, and `not_attempted` is not independent proof that the native queue has no matching item. Do not start another publication solely on those fields.

### Correlation and intended result

- Source: https://t.me/kursh_kosa/16271
- Destination: `max_lovekenig_announcements`.
- Requested schedule: **2026-11-06 09:30 +02:00**, equivalent to **2026-11-06 07:30 UTC**.
- Media: six source photos, retained in source order.
- Operation: `op_66c35e62634d4bf7ae4ab96aea96ba99`.
- Publication: `pub_60f02beaa4c7417eb50b8fbfe02bedf9`, revision 1.
- Attempt: `attempt_18bb936a1a114ac386560044ae09e339`.

### Latest observation

The original operation reached terminal **scheduled**, with `operation_complete:true`, `observed:provider_scheduled`, and unchanged attempt identity. Its provider readback at **2026-11-05T20:59:19.923508Z** recorded `requested_at = effective_at = 2026-11-06T07:30:00Z` and native item `item_d213ed30621948cc9110aa833ddaa694`.

The original receipt's `media_check:provider_identity_only` alone did not verify all six photos. A separate read, operation `op_f15700799956473fbc58ac3b3fd6fb63`, subsequently completed **verified**, `operation_complete:true`. At **2026-11-05T21:00:26.747580Z**, its current native queue contained exactly one matching announcement with matching text, `scheduled_at:2026-11-06T07:30:00Z`, and six media entries at existing positions 0 through 5. The response was complete (`truncated:false`, no next cursor). The independent read returned `ref/queue_ref:item_a0d82eec176a41a2860e84c5f7e66af5`.

The two reads returned different item-reference strings; do not assume those opaque references are stable provider IDs or infer a duplicate from the difference. The independent complete queue showed one matching announcement. This verifies text, schedule, media count and ordered positions, **not pixel/hash identity of each photo**. Prepared originals were retained and visually inspected before sending.

This is a recovered first-execution failure, not a terminal publication failure. No additional publication command was submitted during diagnosis. Do not republish this announcement: inspect and reconcile the original operation/native item first. Successful recovery does not establish that the cancellation defect is fixed.

## Impact

The MAX placement eventually recovered to provider-confirmed scheduled status. The incident concerns initial cancellation, delayed completion and retry reliability before the requested publication time, not a missed deadline or service-wide outage. Independent native queue verification established one matching scheduled announcement with six media entries; per-photo pixel/hash verification remains outside this evidence.

Telegram Announcements, VK Announcements and VK Afisha were scheduled independently by operation `op_1485d704cece4e02af90d5e6b1644ba2`. Those successful placements must not be recreated, edited or cancelled as a side effect of investigating MAX.

## Timeline

All times below are **2026-11-05 UTC**, from the provider diagnostic ledger. Durations are reported measurements, not an inferred breakdown of exclusive CPU or network time. Nested phases overlap and must not be summed as independent work.

| Time (UTC) | Evidence |
| --- | --- |
| 20:53:55.794 | Command durably accepted; no provider effect yet. |
| 20:53:55.974 | Worker claimed command. |
| 20:54:18.303 | Preflight completed in 22,313.859 ms after successful account/navigation/target checks. |
| 20:54:18.366 | Execute started. |
| 20:54:31.608 | Native queue phase completed in 1,263.953 ms. This is a phase completion, not a post-submit receipt. |
| 20:54:50.119 | File upload completed in 7,762.492 ms. |
| 20:55:33.083 | Rich text completed in 41,676.380 ms. |
| 20:55:33.111 | Compose completed in 54,579.339 ms, including nested preparation. |
| 20:55:35.979 | Schedule menu completed in 2,826.787 ms. |
| 20:55:41.740 | Calendar completed in 5,748.935 ms. |
| 20:55:42.164 | Stage changed to submitting. |
| 20:55:42.172 | Another account check started. |
| 20:55:48.489 | Account check failed with CancelledError after 6,310.291 ms; dispatched:false. |
| 20:55:48.516 | Execute failed with CancelledError after 90,151.453 ms; dispatched:false. |
| 20:55:48.535 | Provider command failed; event stage finished/status blocked. This event did not make the enclosing operation terminal. |

The same attempt was subsequently re-entered. Second execute started at **20:57:08.570542Z**; its dispatch marker was recorded at **20:58:31.136752Z**, schedule_submit completed at **20:58:36.742112Z**, and successful provider readback was observed at **20:59:19.923508Z**. These observations distinguish the recovered terminal outcome from the intermediate failure below.

The first returned status after the failure still had `state:running`, `operation_complete:false`, delivery `state:accepted`, `stage:waiting_connection`, `observed:not_attempted`, `sync_status:pending`, `applied_revision:null`, `desired_revision:1`, `retry_safe:false`, and missing check `provider_command_failed`.

A separate native-queue read before submission, operation `op_207ffd431ed842b995fefa621cc6a305`, completed at 20:52:30.690 UTC with one unrelated scheduled item. It is a pre-operation baseline only and cannot rule out later effects.

## Root Cause

**Unknown.** No code-level causal diagnosis, deployment revision verification or host inspection was performed for this documentation task.

Working hypotheses for the responsible engineer:

1. **An enclosing budget near 90 seconds may cancel execute.** The measured 90,151 ms is suggestive, not proof of the configured timeout or its owner. Inspect cancellation propagation and the worker/provider/browser time budgets on the actual deployed revision; distinguish timeout from worker shutdown, task cancellation or transport interruption.
2. **Repeated account/target checks and composition may consume that budget.** Multiple checks succeeded before the final cancelled check. Rich-text preparation alone took about 41.7 seconds. Determine which checks are mandatory, which are repeated unnecessarily and which resources were awaited. Do not remove account/target identity or permission checks to obtain a faster path.
3. **Retry behavior needs reconciliation review.** Confirm why the same attempt was re-entered, which durable before-effect checkpoint admitted it, whether native queue reconciliation preceded each possible submit and what bounds stop repeated work.

The observed cancellation does not establish expired authentication, a MAX outage, invalid media, calendar failure or a locator regression. Successful phase completion also does not prove that all six media items persisted in MAX.

## Fix

`Not done`. This report proposes investigation and acceptance checks, not an implemented fix.

Immediate safe handling:

- Read the original operation and all progress pages, retaining the same publication/attempt correlation.
- Read the **current provider-native scheduled queue** for the exact destination; match intended text, six photos/order and schedule, and inspect live posts if the scheduled time has passed.
- Treat an incomplete, stale or truncated queue read as inconclusive.
- If a matching native effect exists, reconcile it into the original publication rather than submitting again.
- If no matching effect is established, follow the canonical recovery admission contract. `retry_safe:false` is not permission to repeat the publish command.
- Preserve native-only scheduling and the independent Telegram/VK placements.

Relevant canonical contracts:
[Social operations](../../features/social-operations/README.md),
[MCP contract](../../features/social-operations/mcp-contract-v1.md),
[Provider diagnostics](../../features/social-operations/provider-diagnostics.md),
[Acceptance tests](../../features/social-operations/acceptance-tests-v1.md).

Before changing behavior, read the deployed implementation and current canonical requirements. Mark the affected canonical acceptance item appropriately before implementing; this incident is a regression contract, not a replacement requirement document.

## Regression Checks

The fix should demonstrate all of the following:

1. Six-photo native scheduling succeeds with rich text and the requested timezone conversion. Provider readback confirms one matching scheduled item, all six images in order, text/entities and 07:30 UTC schedule.
2. Slow account checks, composition and calendar interactions produce bounded, actionable progress rather than an unbounded running/pending loop.
3. A pre-dispatch cancellation preserves a truthful durable state and admits recovery only when its existing safety conditions hold.
4. Cancellation immediately before submit, during submit and after a possible provider effect cannot cause duplicate posts; ambiguous outcomes reconcile native state first.
5. Worker restart/reclaim preserves attempt identity and progress pagination, without treating an old blocked event as a final operation result or treating not_attempted as a native absence guarantee.
6. Successful recovery does not alter the three independent Telegram/VK scheduled placements.
7. Diagnostics preserve timings, safe cancellation category, dispatch boundary and correlation, without raw DOM, credentials, session data or private links.

Use an authorized test destination or explicitly authorized production canary. Offline tests alone do not establish production acceptance. Record exact tests, deployed revision, native readback and user confirmation separately.

## Release Evidence

- This change is an incident document only.
- No application code, runtime settings, deployment or new provider effect was changed to prepare it.
- No fix, test-suite run, production rollout or user acceptance is claimed. Native scheduling and independent queue readback are verified at the scope stated above; these do not close the reliability incident.
- Evidence summarized from operation status/progress and provider-native reads; raw run dumps and artifacts are intentionally not committed.
- Public source URL and technical correlation IDs are included for lookup. Credentials, cookies, tokens, private URLs and unrelated content are excluded.

## Follow-Ups

- Responsible MAX engineer: establish the cancellation owner and actual timeout settings on the deployed revision.
- Preserve the recovered terminal outcome and native item identity. Independent queue verification is complete at the scope above. Preserve its evidence; do not create a replacement publication.
- Implement and verify the smallest compliant fix, update canonical docs/changelog when behavior changes, and append release evidence here.
- Close only after regression checks and live acceptance are established; an eventual successful retry alone does not prove the cancellation/retry defect is fixed.

