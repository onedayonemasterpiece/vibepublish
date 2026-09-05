# Automated acceptance tests — VibePublish v1.2

> Current remote delivery: **partial, not a runnable release**. The implemented
> behavior and historical test counts below describe the complete archived source.
> Three production modules remain undelivered; current evidence and exact boundaries
> are in [runtime status](../../operations/social-runtime.md).

Date: 2026-09-04. Owner functional requirements: Fixed. Runtime tests below: Not done until their actual implementations/runs exist.

## Executed versus designed

Executed locally in this design session: `python -m unittest discover -s tests/contracts -p 'test_*.py' -v` with jsonschema 4.26.0. Result: **22 unittest methods passed**, 16 schemas, **125 golden calls** (105 existing + 20 forwarding/profile cases), **44 negative calls** (30 existing + 14 new). The baseline 14 methods were also rerun before editing. These are schema, catalog-projection and fixture checks, not evidence of live providers, database crash recovery, model accuracy or a working server.

Canonical executed sources: `tests/contracts/test_social_mcp_design.py`, `tests/contracts/test_forwarding_profiles_design.py`, `contracts/task_corpus_v1.py`, `contracts/social_mcp_v1.py`. Negative and runtime-oracle labels are not substituted for executable security tests.

## First executable core checkpoint

`tests/runtime/` adds real SQLite, independent subprocess crash/recovery and
concurrent worker cases, current-authority/cache/source/asset denials, fake
native queues and lifecycle readback, profile CAS/routing/idempotency, incremental
receipts, and actual MCP SDK/HTTP tests. See the runtime runbook for executed
commands/counts and the exact source-delivery boundary. The test matrix below
remains the complete target, not a claim that every case is implemented.

## Test layers and implementation ownership

| Layer | Implementation target | Owner | Gate |
|---|---|---|---|
| Contract | Existing tests/contracts plus exact skill examples and transport schema validation | Core window | Every change |
| Domain/storage | Real temporary SQLite, independent connections/processes, fake clock, fixed failure injection | Core window | Before provider integration |
| Provider contracts | Scripted fake providers AND actual adapters against recorded/synthetic safe responses | Core window; MAX adapter by MAX task | Every adapter |
| Browser | Real Playwright/Chromium on sanitized local fixture pages; later live MAX account | MAX task | Before MAX capability activation |
| Service integration | Actual MCP/HTTP server, client session, worker process and SQLite; fake remote providers | Core window | Before deployment |
| Live canaries | Designated provider test destinations and actual provider readback | Explicit integration task | Before capability advertised live |
| Weak-agent workflow | Versioned corpus against real weak model and fake service | Later authorized benchmark task | Before claiming agent usability |

Use one Python test suite/CI, not one workflow per requirement. Run offline checks on GitHub-hosted runners; no self-hosted runner. No live credentials in pull-request jobs. Normal CI must not post/delete anything on social networks. Missing optional live credentials means NOT RUN, not PASS. Do not fake all browser behavior with mocks and call it a browser test.

## Core acceptance matrix

Each ID becomes an actual parametrized test/scenario with explicit expected provider call count, durable rows and observable receipt. Proposed test paths below are targets, not files claimed to exist now.

| IDs / target | Stimulus | Required proof |
|---|---|---|
| C01-03 tests/unit/test_request_identity.py | Same key replay, conflicting key, mutable URL/set | One command identity; no repeated side effect; frozen members and asset hashes |
| C04-06 tests/integration/test_dispatch_crashes.py | Kill process before dispatch marker, after marker, after remote effect before receipt | Safe before-attempt retry; ambiguous attempts reconcile; never duplicate |
| C07-08 tests/integration/test_worker_fencing.py | Two workers, expired lease with old request still in flight | One effective dispatch owner; stale worker cannot commit or re-send |
| C09-11 tests/integration/test_progress.py | Telegram finishes, VK uploads, MAX stalls; reconnect midway; expired cursor | Initial receipt before remote completion; first child visible independently; durable ordered events; no silent event gap |
| C12-14 tests/integration/test_native_queues.py | Scheduled post, unsupported scheduling, time passes while all service processes stopped | Native submission now; no local send-at timer; absent native capability blocks, never falls back |
| C15-17 tests/integration/test_lifecycle.py | Reschedule/cancel, concurrent publication at due time, external manual edit | Existing remote item changed/read back; published is not cancelled; conflict is explicit |
| C18-20 tests/security/test_read_boundaries.py | Partner reads others' queued posts in bound channel; unbound channel; owner dialog read | Allowed channel full contents; unbound denied before fetch; owner obeys real provider visibility |
| C21-23 tests/security/test_assets_cursors.py | Cross-tenant asset/candidate/token/cursor/cache; revoke binding after cached read | No data/existence leakage; current authority enforced on all projections |
| C24-26 tests/security/test_media_ingress.py | Private-IP URL/redirect, MIME mismatch, decompression bomb | Rejected before remote posting; bounded resource usage |
| C27-29 tests/integration/test_history_metrics.py | Find own posts/forwards; refresh exact statistics; remote missing item | Indexed history; observed_at/freshness; missing is not zero or proven deletion |
| C30-32 tests/integration/test_visual_resume.py | Repeated selection, wrong-tenant candidate, expired schedule after generation | Selected hash/revision fixed; one authorized continuation; no delayed local send |
| C33-35 tests/integration/test_api_mcp_parity.py | Same intent through HTTP and MCP, hidden tool direct call, disconnected client | Same service semantics; server auth independent of catalog; accepted task survives connection loss |
| C36-38 tests/integration/test_backup_restore.py | DB backup with WAL, restore, disk full | Consistent history; restore writes disabled until reconciliation; no false accepted receipt |

Use virtual time for deadlines and real process termination for durability cases. A unit fake cannot prove crash persistence; a real SQLite connection in one process cannot alone prove cross-process fencing.

## Forwarding and editorial profiles

| IDs / target | Stimulus | Required proof |
|---|---|---|
| F01-03 tests/adapters/test_native_forwarding.py | TG permalink, VK permalink, incoming forwarded item_ref | Actual native compiler call; preserved source relation and item mapping; no rewrite/upload fallback |
| F04-06 tests/adapters/test_forwarding_media.py | Album link, single-message selection, provider skips one source item | Exact grouping/order/count; skipped items cannot be all-success |
| F07-09 tests/security/test_forward_sources.py | Exact external public source, private operator-only source, protected source | Bounded public source lookup; no neighbor feed; caller authority for private; no protection bypass |
| F10-12 tests/adapters/test_forwarding_failures.py | Mixed-platform target set, unknown submit, source changed after review | No partial preflight mutation; readback-only uncertain recovery; conflict before forwarding changed source |
| F13-14 tests/adapters/test_forward_schedule.py | TG native scheduled forward; VK scheduled repost unsupported | Real native queue or explicit unsupported; no timer or immediate fallback |
| F15-17 tests/integration/test_editorial_profiles.py | Save purpose/notes, personal CAS conflict, another principal's profile | Durable metadata only; correct revision; no native channel/grant modification |
| F18-20 tests/integration/test_routing_context.py | Unique permitted channel, ambiguous match, stale routing_revision | Explicit to from model; no guessed broad fan-out; refresh stale context before dispatch |
| F21-22 tests/contracts/test_skill_examples.py | core/all/forwarding/destinations sections; stale skill/version | Actual canonical text and schema-valid examples; dynamic rights/profile cache not bypassed |

Agent choosing a channel correctly is a workflow benchmark assertion, not something JSON validation proves. Server checks enforce exact destinations and policy; model tests separately assess whether it selected the right eligible profile for the user's request.

## MAX-specific tests

The separate [MAX handoff](../../handoffs/max-web-codex-20260904.md) owns M01-M12: wrong account, duplicate display names, virtualized channel/queue list, rerender before click, upload failure/order, delayed image/video processing, expired login, pre-submit crash, post-click crash, duplicate candidate readback, concurrent profile claim and ordinary native queue edit/reschedule/cancel. Sanitized HTML/accessibility fixtures are allowed; production cookies, tokens, private unrelated messages and screenshots must not enter Git.

Critical combined scenario: start one core operation for three providers, make MAX wait inside a controlled browser fixture, and observe real MCP status output for Telegram/VK before releasing MAX. Then kill/restart the worker after MAX submit and prove the same operation is reconciled without another click.

## Live evidence gates

L01: independently configured Telegram/VK write + media readback. L02: native scheduling verified in provider UI/queue. L03: stop every VibePublish process before due time, then observe publication at the provider (external observer/manual fixture account); service restart must not send it. L04: edit/reschedule/cancel existing native item. L05: protected/unauthorized source denied. L06: native forward/repost origin observed. L07: MAX profile/account/queue behavior verified live. L08: actual imagegen artifact return. These are targeted test destinations approved by the owner, not public marketing channels selected by the agent.

Reports record exact repo SHA, dependency/browser versions, fixture versions, command, test counts/pass/fail/skip, provider identity reference, artifact/evidence hashes and unresolved limitations. Never change a compatibility test merely to turn a defect green. Runtime, live-provider and weak-agent readiness remain separate verdicts.
