# MAX Web — current task and verified baseline

Updated: 2026-09-05. Branch: `work/vibepublish-max-web-20260904`, [PR #2](https://github.com/onedayonemasterpiece/vibepublish/pull/2).

**Implementation status: Partial / Not confirmed by user.** The latest code baseline remains an offline fixture driver and actual-core bridge. The new task below has been prepared, not executed. This documentation change does not turn fixture coverage into live MAX support.

## Current authority and continuation

The owner has now authorized live MAX work in three named destinations using the already authenticated session. The authoritative continuation and exact permission boundary are in [MAX live completion package](../handoffs/max-web-live-completion-20260905.md), including L01–L16 and GitHub reproduction requirements.

This replaces the previous blanket prohibition on live reads/writes/canaries and the limited next step of implementing the core bridge. It does NOT authorize unrestricted production publishing, auth changes, MAX API, imagegen, migration, global deployment or merging the PR.

- **Тестовая группа:** all relevant social-operation test scenarios on task-owned test objects, including immediate publication and native scheduled release.
- **Ух ты, Калининград!** and **Полюбить Калининград:** reads of feeds/queues and work on task-owned native scheduled probes only; no intentional public test publication and no changes to existing editorial objects.
- Names are discovery inputs; actual account/chat identities must be resolved before effects. The packet defines the 24-hour safety margin, one active probe per real channel, exact cleanup and failure reporting.
- Reuse the existing authorized MAX session. Do not log out, clear state, copy credentials or implement login now. Future onboarding is via QR with human approval; no QR implementation or login experiment is part of this task.

Do not request the same already granted permissions again. If identity, profile access or a provider capability is genuinely unavailable, report the specific blocked case while continuing independent safe work. Do not substitute another target or local scheduler.

## Preserved baseline and evidence boundaries

The pre-task MAX source checkpoint is `7e996e08fdcf1aa2295b07a4b3510d865c6fcee1`. It contains `adapters/max/bridge.py:MaxAdapter` importing the actual ProviderAdapter/native helpers, the original `FixtureDriver` with its loopback restriction, process-exclusive profile locking and uncertainty handling. There is no production selector set/factory at that checkpoint.

Historical evidence, not a run performed by the preparation of this new task:

| Layer | Previous result | Meaning |
|---|---|---|
| MAX-only remote CI | 37 passed, two actual-core modules skipped; 14 + 8 contract tests | Original fixture checks, not real MAX or remote full-core integration |
| Local verified core archive + MAX overlay | Agent reported 55 MAX tests, 0 skips; 24 contract tests + 193 subtests | Actual MCP ClientSession/worker/SQLite integration, fake TG/VK and real Chromium on a synthetic page |
| Live MAX | Not run | Still requires the new authorized task |

[Historical CI run](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/33951087890) and [complete prior runbook with original commands and evidence](https://github.com/onedayonemasterpiece/vibepublish/blob/7e996e08fdcf1aa2295b07a4b3510d865c6fcee1/docs/operations/max-web.md) remain available. Its old permission paragraphs are historical, not a competing current instruction.

The useful integration behavior must survive: awaited core progress/checkpoint/before_effect; translation of driver `running` status to core `started`; attempt/plan-bound recovery baseline; native identity/namespace conversion; ordered input-asset provenance without fabricated transcoded hashes; scoped read pagination; real process-kill recovery without duplicate effects. Existing fixture safety assertions must not be weakened to make live tests pass.

## Local core dependency

The previous agent moved the actual ZIP to:

`/home/dev/projects/vibepublish-max-web/artifacts/codex/max-core-integration-20260905/vibepublish-native-visual-20260905.zip`

Recorded ZIP: 875577 bytes, SHA-256 `5651e09a046806b0bfd1fcfb7a92998c22fd9e1c902e1d7f28b53db5fdbe1933`.
LOCAL core HEAD: `870e2a4304c57ef5dd7152de63df1db6431a942b`.
Port last-change commit: `25de851b911d02fc9ece2a7e193743758bfa48c1`; SHA-256 `4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`.

Recheck the file and manifest on the host, or use a subsequently officially delivered compatible core commit after fresh-reading PR #1. Do not assume this path is mounted in a different environment. `tests/adapters/max/assemble_core.py` remains the existing local-only assembler. Do not push the blocked core payload through this task or substitute the old seed port. An actual-core CI prerequisite cannot be hidden as a successful skip.

## Required implementation delta

The new package requires the real selector/factory path and positive text-only publication, native schedule/readback, edit, media-preserving reschedule, cancel/delete outcomes. The fixture's unconditional unknown outcomes are not completed product capabilities. Group and channel support must be observed separately; unsupported provider behavior stays explicitly unproved rather than being replaced by local delivery or content copying.

Exact target identity must survive changes in chat order, search results, unread/pinned state and DOM re-rendering. A changed display name or list index must never redirect an operation. Preserve the invariant that an uncertain effect is observed, not repeated. No public test release in real channels is permitted even to improve coverage of a group-only capability gap.

## Reproducibility and final report

Follow the packet's L01–L16 matrix. Run the same live driver/selector recipe against sanitized, stateful observed-UI replay, plus the original fixture suite. Include all six permutations of the three test targets, changes between resolve and click, duplicate names, virtualized lists, media delays, callback failures and post-effect restart. Mock page objects or a second simplified driver do not prove this requirement.

Use the existing GitHub-hosted CI, with exact tested source SHA and pinned browser/dependencies. CI must never connect to real MAX or possess session state. Commit safe fixture source/generators and tests, not private HAR/DOM/traces, credentials or the core archive. Keep local live evidence protected and reference it through a sanitized report.

Report separately: live scenarios, same-driver replay, actual-core local/remote integration, pass/fail/skip/unknown, remaining unsupported capabilities and exact cleanup results. A negative safety test is not a positive functional pass. The expected real-channel cleanup outcome is zero task-owned scheduled probes; unresolved objects and deadlines must be reported immediately.

The task-preparation change ran no Codex agent, provider action, deployment or runtime tests. Record new execution results only after the implementing agent actually produces them.
