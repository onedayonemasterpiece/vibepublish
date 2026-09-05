# MAX Web — current task and verified baseline

Updated: 2026-09-05. Branch: `work/vibepublish-max-web-20260904`, [PR #2](https://github.com/onedayonemasterpiece/vibepublish/pull/2).

**Implementation status: Partial / Not confirmed by user.** The latest code baseline remains an offline fixture driver and actual-core bridge. The new task is partially executed: observed read/navigation code and live reads now exist; publishing is still unimplemented. See the execution checkpoint below.

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

The task-preparation commit ran no runtime tests; the later execution checkpoint below records the implementing task separately.

## Execution checkpoint — observed UI, 2026-09-05 (package NOT complete)

The owner clarified that the third destination is **«Полюбить Калининград Анонсы»**.
Three distinct native chat routes are now recorded in a mode-0600 local allowlist.
The account binding currently uses the actual settings UI phone identifier; a
numeric MAX user ID has **not** been established. No phone/target IDs are published.

The bridge reported zero active sessions and a protected configured `max` profile.
Host process metadata resolved that alias to the existing profile; its old Chromium
owner PID was absent. Reuse acquired the bridge-compatible exclusive ownership
record, ProfileLane and Chromium's own profile lock. No live owner was killed,
profile copied, QR obtained, login repaired, or shared bridge stopped. Task-owned
browsers were closed after each bounded read. Live Chrome was 151.0.7922.34;
Playwright/CI use the separately pinned test dependency, not that live binary.

### Delivered code scope

- `adapters/max/live.py:RealMaxDriver`: the actual personally observed **read and
  navigation subset**, separate from unchanged `FixtureDriver`. Direct native
  routes, exact scoped headers, explicit account callback, bounded operations,
  namespace checks, no sidebar-message extraction. It exposes **no submit path**.
- `adapters/max/live_session.py`: explicit existing-profile **read-only factory and
  CLI**, private allowlist/output, ownership refusal, no default environment/profile
  discovery or auth bootstrap. It is **not yet wired into ProviderAdapter**.
- `tests/browser/max/observed/`: independently authored stateful structural replay
  running that same read/navigation code. All six target orders persist across
  navigation. It checks route drift during awaited checks, duplicate/disappearing
  title rows, search-excerpt false positives, re-render and wrong namespaces.
  Rename currently fails closed; positive automatic rename continuity is missing.
- `adapters/max/evidence.py`: lossy structure-only exporter. Dynamic text, IDs,
  asset URLs, scripts, arbitrary attributes/classes are dropped. Artificial-secret
  tests are not a general certification of arbitrary future captures.

No publishing implementation or complete same-driver acceptance is claimed by
these names. The original bridge's fixture-only checks remain intact rather than
being weakened to expose an unproved live executor. Core/port/TG/VK/MCP/VisualService
are unchanged. This is an unfinished checkpoint, **not delivery of the whole package**.

### Live findings and failures

The successful same-code reads saw: group feed 8 rendered rows; first channel
feed 17 / queue 7; clarified second channel feed 30 / queue 8. All projections
explicitly carry `complete=false` and missing native-ID/pagination checks. These
numbers are screen observations, not total queue sizes. Raw contents/media URLs
remain in protected local artifacts; none are included in replay or CI artifacts.

Observed group message menu includes native message-link copying. The examined
channel queue menu includes “Изменить время”, “Редактировать”, “Удалить”, but not
message-link copying. No stable queue ID was found in the inspected DOM/menu;
**do not fabricate an ID from text/time or use visible absence as cleanup proof**.
The group had no queue-entry button on the observed screen; the empty-composer
context click opened no scheduling menu. This does NOT establish native scheduling
unsupported for a populated composer. No populated-composer test was performed.

Two discovery failures were investigated rather than bypassed: DOM-ready is not
application-ready, and the actual title contains leading whitespace. An anchored
raw-text regexp failed while the scoped whitespace-normalized exact locator worked.
A separate early account-check timeout was also observed. The factory's aggregate
read deadline was raised from 10 to 30 seconds; this is bounded waiting, not evidence
that all startup/tab-race behavior is solved. Targeted official
[Playwright navigation](https://playwright.dev/python/docs/navigations) and
[locator](https://playwright.dev/python/docs/locators) references were checked after
repeated failures. No further guessed selector was used to authorize a mutation.

**Social effects in this checkpoint: 0.** No new messages, schedules, edits or
removals; therefore no task-created scheduled probes remain in either channel.
This is not a positive cancel/cleanup test. Local registry:
`artifacts/codex/max-live-20260905/` (private, not committed).

### L01–L16 checkpoint (new real-driver package, not historical fixture claims)

`UNKNOWN` below means partial evidence, not a positive capability pass.
Remote results are recorded separately in PR #2 with exact source SHA/CI readback.

| Gate | Live | Observed-code replay | Actual-core / remote scope | Concrete remaining work |
|---|---|---|---|---|
| L01 | UNKNOWN: existing auth, 3 routes, UI phone | PASS: explicit-session/owner refusal tests | New live factory not integrated with core | Numeric account identity and robust live binding |
| L02 | UNKNOWN: incomplete reads in all 3 | UNKNOWN: bounded screen projection only | Original fixture read integration retained | Stable item/queue refs and complete pagination |
| L03 | NOT RUN | NOT RUN | NOT RUN for real driver | Causal text-only receipt, edit, exact delete |
| L04 | NOT RUN | NOT RUN | Original synthetic media tests only | Real uploads and media-preserving lifecycle |
| L05 | NOT RUN | NOT RUN | NOT RUN | Video/formatting recipe and positive tests |
| L06 | NOT RUN | NOT RUN | Original synthetic scheduling only | Queue identity, cleanup proof before channel probes |
| L07 | NOT RUN | NOT RUN | NOT RUN | Verify group schedule with content; native release |
| L08 | NOT RUN | NOT RUN | Original fixture SIGKILL tests only | Real-driver receipt/recovery and process-kill replay |
| L09 | NOT RUN | NOT RUN | Original ClientSession/worker tests only | Real-driver bridge and combined regression |
| L10 | NOT RUN | NOT RUN | Original fixture ambiguity/CAS only | Same-live-code attribution and editor CAS |
| L11 | NOT RUN | UNKNOWN: read account/target/mode guards | Original callback/revoke tests only | Real mutation guards and refusal zero-effects |
| L12 | NOT RUN: no own message drift | UNKNOWN: six orders/native navigation pass | No new core claim | Reordered search/mid-effect permutations |
| L13 | NOT RUN | UNKNOWN: duplicate/disappearing/renamed rows | No new core claim | Positive rename and pin/filter/scroll matrix |
| L14 | NOT RUN | UNKNOWN: scoped re-render/read | No new core claim | Upload/menu/composer lifecycle faults |
| L15 | NOT RUN: no probes created | NOT RUN | No new core claim | Own-probe lifecycle and editorial before/after proof |
| L16 | NOT RUN (CI must be offline) | UNKNOWN: same navigation code only | Full remote core still blocked by missing delivered core | Same publishing-code replay, not just navigation |

### Reproduce without mixing evidence levels

```bash
# Ordinary local/CI: no profile, credentials or real MAX traffic.
python -m pytest tests/adapters/max tests/browser/max -q -ra

# Actual core: verify original ZIP again; output must be a NEW artifacts directory.
python3 tests/adapters/max/assemble_core.py --archive /private/path/to/verified.zip \
  --output artifacts/max-assembled-new
cd artifacts/max-assembled-new
VIBEPUBLISH_MAX_CORE_REQUIRED=1 /path/to/core-venv/bin/python -m pytest \
  tests/adapters/max tests/browser/max --asyncio-mode=auto -q -ra

# EXPLICIT LIVE READ ONLY. Arguments are operator-selected, not environment fallbacks.
# Output directory must already be private; output file must not exist.
python -m adapters.max.live_session --live-read --profile /approved/existing/profile \
  --executable /approved/chrome --allowlist /private/allowlist.json \
  --output /private/artifacts/new-read.jsonl
```

The allowlist shape is `{"account_phone":"<exact private UI value>","targets":{
"<native route ID>":{"alias":"<confirmed UI title>","policy":"test_group or scheduled_only"}}}`.
Policies currently label read bindings; they are **not implemented publication
permissions**, because no live mutation method exists. Never wire this partial
factory into core as a supported publishing capability.

The first assembled run of this checkpoint ended **97 passed / 1 failed**:
`httpx.ReadTimeout` in the preserved scheduled MCP progress/crash scenario. The
harness supplied an HTTPX client with its default 5-second inactivity timeout,
but requested a 10-second status long-poll and declared a 30-second ClientSession
budget. The MAX test client now explicitly uses read timeout 30 / connect 5;
the independent **5-second first-event assertion remains unchanged**. This is a
test-transport correction, not a core/worker edit or a weakened early-progress
requirement. [HTTPX timeout contract](https://www.python-httpx.org/advanced/timeouts/).
Failed and subsequent logs are retained locally; only completed reruns count.

Privacy correction: an early overly broad diagnostic enumerated sidebar button
previews, including unrelated snippets, in local tool output. That diagnostic
was stopped; no such output is included in committed fixtures or CI artifacts.
The saved driver restricts extraction to bound main panes and title-only discovery.
Do not repeat global `button.innerText` / `body.innerText` dumps on authenticated UI.

### Completed verification of code checkpoint

Code/test SHA: `a18fa1c640596c4818b9c0405d986e4e51e74e6b`, pushed to the existing
MAX branch. All **11 changed files** were read back byte-for-byte from an independent
GitHub clone checked out detached at that exact SHA. No second feature branch.

- New safety + observed-navigation suite: **44 passed**, no skips.
- Local verified archive + exact MAX overlay: **99 passed**, zero skips, 225.77s;
  includes the preserved 55 actual-core/fixture cases, not live-driver MCP wiring.
- Archived contract regression: **24 passed + 193 subtests**, 3.55s.
- [GitHub-hosted PR CI 33954798092](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/33954798092):
  **success**; inspected logs: **81 passed, 2 skipped core modules**, 80.19s,
  plus **14 + 8** main-based contract checks. The 81 are the original 37 plus 44
  new tests. No publishing-code replay or remote full-core claim.

The acceptance source projection has 125 files (103 original core sources plus
MAX-owned source/tests), canonical sorted JSON source-hash manifest SHA-256
`336be2bd667470f9ee6e8c2654689803b84f9eaf4d770ffc5c123a9f0af48aa0`.
This is explicitly a **manifest hash, not a Git tree SHA**. Inputs remain core
`870e2a4304c57ef5dd7152de63df1db6431a942b` and the code SHA above. All 103 source
hashes and port `4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`
were rechecked unchanged. Local results reuse installed dependencies; no clean
requirements.lock claim. At the final fetch PR #1 advanced to
`73345b450793b92dfa1f3992713b4b7d7541c9b2` with dependency/SDK verification work;
its full runtime is still not remotely delivered. MAX did not import that payload.

Replay keeps provider event counters outside driver state and aborts every
non-loopback browser request. Passing tests assert **zero attempted outbound real
MAX requests and zero social effects** for this read-only subset. Source review
and binding/sentinel checks found no private binding values in published files.
This does not claim comprehensive certification of arbitrary future captures.

Final documentation-only SHA and any later CI readback are recorded in PR #2;
this code checkpoint remains distinct from those documentation updates.

### 2026-09-05 publishing attempt — FAILED, quarantine retained

Continuation of [owner clarification 5550746580](https://github.com/onedayonemasterpiece/vibepublish/pull/2#issuecomment-5550746580).
This is **not** the requested first completed text lifecycle or L01–L16 acceptance.

An experimental, locally overlaid RealMaxDriver writer submitted one marked text
probe in the authorized test group through a genuine MCP ClientSession, original
Application/worker and SQLite ledger. MCP acceptance took 0.176 seconds. An
independent SQLite connection verified the exact dispatched attempt/checkpoint
before the UI Send click. This proves dispatch ordering, **not successful native
receipt attribution**.

Implementation error: the writer allowed Send before its causal receipt recipe
was implemented. Passive WebSocket recording captured no own-intent frames;
retained browser HTTP requests contained no matching own send receipt either.
The new marked outgoing row's provider-issued link was copied through its scoped
UI menu and read back a second time with the same reference and text. This is
positive item observation, but is not sufficient causal attribution. The worker
therefore committed **outcome_unknown**, and the persistent profile quarantine
was retained. No retry, ledger reset, fabricated receipt or manual mutation
bypassing the quarantine was performed. The session was closed gracefully without
logout or copying its credentials.

**Remaining probes: one marked immediate text object in the test group; cleanup
not performed. Zero new objects in either authorized channel.** Private exact
reference, intent, original ledger, durable-before-effect evidence and prototype
patch are retained under `artifacts/codex/max-publish-20260905/` (not in Git).
Do not delete these recovery inputs or remove `.vibepublish-uncertain` to resume
writes. Current core has no authorized terminal-unknown resolution path that can
turn this incomplete receipt into verified attribution. Coordinate recovery with
core rather than rewriting its ledger or borrowing another connection/profile.

The unsafe experimental bridge/writer was preserved privately, not shipped. The
existing fixture/fake guard remains unchanged. RealMaxDriver now explicitly
rejects mutation *before* composer changes, callbacks or Send when the causal
receipt recipe is unverified; arbitrary publishing flags cannot enable it.
Read-only reconciliation does not clear an unknown attempt. Added same-driver
browser regressions test these failures with independent zero-effect counters;
they are **negative safety tests**, not positive publication or lifecycle replay.

The first requested vertical remains FAILED: publish UNKNOWN; exact link/text
read observed; core edit/delete NOT RUN. Media lifecycle, native scheduling,
channel cleanup, native release, rich/video/forward, new-driver crash recovery
and new-driver actual-core replay remain NOT DONE. The immediate write blocker
is the unresolved attempt plus missing causal receipt recipe. Queue/native media
identity and lifecycle selector recipes remain separate implementation gaps.

Inputs used for this failed live run: complete archived core
`870e2a4304c57ef5dd7152de63df1db6431a942b`; all 103 source hashes and patch hashes
reverified by `tests/adapters/max/assemble_core.py`; port SHA unchanged
`4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`.
Fresh-read PR #1 was `76ad2c554fe5866ddd23f79154095d281e099154`; its partial runtime
was not substituted for the complete archive. A later narrow check loaded the actual port from PR #1 commit
`b84c2082ca771a3e9fd72853011d35c7396c1c52` in a separate process and verified
`MaxAdapter._remote` constructs its `RemoteItem` with default `entities_json="[]"`.
That port SHA-256 is
`0bf0ca135d42c3535da117589140bf180ba979e1296301d5415a8c7a94517174`.
This is constructor compatibility only, not full partial-runtime integration or
rich support; no core source in either assembled tree was replaced.

Diagnostic reference: [Playwright WebSocket events](https://playwright.dev/python/docs/api/class-websocket)
and [page WebSocket creation event](https://playwright.dev/python/docs/api/class-page#page-event-websocket).
A listener attached after socket creation is not a retrospective receipt log;
these docs do not establish the MAX transport or its receipt contract.

Checkpoint verification commands (safety only; final counts/remote SHA/CI readback
in PR #2):

```sh
PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright artifacts/max-venv/bin/python -m pytest tests/adapters/max tests/browser/max -q -ra
python3 tests/adapters/max/assemble_core.py --archive artifacts/codex/max-core-integration-20260905/vibepublish-native-visual-20260905.zip --output artifacts/codex/max-publish-20260905/safety-tree
# From the new safety-tree, using the existing core virtualenv:
PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright VIBEPUBLISH_MAX_CORE_REQUIRED=1 /home/dev/projects/vibepublish-max-web/artifacts/core-venv/bin/python -m pytest tests/adapters/max tests/browser/max --asyncio-mode=auto -q -ra
```

Initial local test launches failed because the environment selected an absent
browser cache, not because of selector behavior. The corrected commands select
the already installed matching Playwright 1.58 Chromium build 1208 at
`/opt/ms-playwright`; no profile or browser version was changed for these tests.
The live experiment used the explicitly selected existing Chrome 151 binary
(build 1234), separately from replay. Original fixture integration coverage is
retained; it does not prove the failed live-driver lifecycle.

The first assembled-tree invocation also omitted the documented
`--asyncio-mode=auto` option: core pytest configuration does not enable MAX async
tests automatically. That invalid invocation was interrupted; the corrected run
uses the existing documented mode without changing core configuration.

The corrected assembled invocation exposed a separate test harness fault: its
credential-scrubbed child environment dropped `PLAYWRIGHT_BROWSERS_PATH`, so
`process-1.log` showed Chromium executable missing before any worker event.
The MAX-only transport test now passes this non-secret browser installation
setting through its explicit allowlist. The first-event deadline remains exactly
5 seconds; HTTPX/core/dispatch logic is unchanged.

Final local corrected results for this safety checkpoint: **87 passed, 2 skipped**
standalone (the unavailable actual-core modules only), **105 passed, zero skips**
archived actual-core/fixture assembly, and **14 + 8** contract checks. The 105
preserve all prior 99 cases plus six negative receipt/quarantine tests; none are
new positive live publishing/core replay. Detached remote checkout of the safety
code ran the 25 observed navigation/receipt-guard tests successfully. Remote CI
and final commit readback are recorded on PR #2 rather than equated with local
archived-core integration.

### 2026-09-05 recovery continuation — original object observed, NOT resolved

Authoritative clarification: [5551577580](https://github.com/onedayonemasterpiece/vibepublish/pull/2#issuecomment-5551577580).

1. **Original post remains**, unchanged in the test group. No edit/delete or new
   Send. Zero channel writes.
2. Original operation is still **outcome_unknown**. No direct SQL repair, new
   connection/profile, worker replacement, deadline reset or fabricated success.
3. The original attempt/digest quarantine remains **byte-identical**. Owned browser
   sessions were closed normally without logout or credential copying.
4. **Positive read-only recovery was exercised live**, first with RealMaxDriver,
   then through MaxAdapter and the actual archived ProviderAdapter types/helpers.
   Both paths reopen the bound target twice and re-copy/check the exact provider
   reference, account, outgoing status, unique loaded task marker and full plain
   content. No effect or core checkpoint hook is called. The original SQLite file
   hash was unchanged before/after each run. This is not MCP terminal-resolution.

The saved chain includes the original immutable core plan/digest/attempt, a
128-bit task marker saved before dispatch (10:57:35.577 UTC), the separately read
SQLite dispatched checkpoint (10:57:53.586), the core reading_back event after
Send (10:57:55.120), the first native reference saved at 10:58:46.752, and its
11:08:35 repeat. New independent driver reads completed at 12:08:55 and 12:09:08;
a subsequent actual-port/bridge read also matched. The core terminal unknown
occurred at 10:59:14; the saved core history, not the old controller's apparent
waiting state, is authoritative. These observations are evidence for historical
attribution validation, not a retroactive verified state. Loaded-row uniqueness
is explicit: this implementation does **not** assert full history completeness.
A network ACK is not required by the contract, and its absence is no longer
presented as the mandatory missing evidence.

#### MAX recovery API and core dependency

`MaxAdapter(..., recovery=RecoveryBinding(attempt_id, plan_digest,
native_reference, task_marker))` accepts an explicitly bound RealMaxDriver for
**reconcile only**. Fixture/fake effects are unchanged. Live prepare/execute are
rejected even for a forged supported capability. `reconcile(request, checkpoint,
hooks)` validates the actual core checkpoint and immutable binding, then returns
an actual `Observation('outcome_unknown', items=(RemoteItem(...),),
missing_checks=('core_historical_attribution_resolution', 'history_completeness'))`.
The item is positive existence evidence, not an adapter-issued resolution.
No checkpoint/fuse release is performed by this live branch. The progress hook
is core-owned; local probes used a nonpersistent collector and prohibited all
persistence/effect hooks.

Still missing: the authenticated, fenced **terminal-unknown observation/resolution
entry point** requested in [core coordination 5551574373](https://github.com/onedayonemasterpiece/vibepublish/pull/1#issuecomment-5551574373),
including append-only resolution persistence and attempt/digest-bound release
acknowledgement. No such shipped endpoint/contract was supplied at core HEAD
`f91f92cf6781c617719721a27f5b6c9015344c60`. MAX does not invent it. If attribution
cannot be resolved, the separate exact-object compensating cleanup path is also
missing. Until one exists, the original object is retained and live mutations
remain blocked. This is a technical dependency, not missing user permission.

Private recovery inputs/results/scripts: `artifacts/codex/max-recovery-20260905/`;
original inputs remain in `artifacts/codex/max-publish-20260905/`. These contain
exact private links and must not be pushed. New results are separate durable local
artifacts, **not core observation/resolution events**.

#### Replay scope

Same RealMaxDriver code runs on the single stateful observed-UI replay. The
native copy-link menu/clipboard recipe is transcribed from the original authorized
object; no invented native-ID DOM attribute or MAX API endpoint. A clipboard
sentinel prevents stale-link acceptance. Nonunique, old/wrong-ID, foreign,
changed-content/media, wrong-account/target and changed-quarantine cases refuse.
Both fresh opens and checks after awaited callbacks reacquire scoped locators.

Six orders have positive exact-reference recovery tests. A real child-process
SIGKILL between observations, followed by restart against the independent
loopback provider state, proves repeated observation without Send, without a
second object and without clearing the fuse. This is a **reader crash**, not a
claim of post-submit writer crash recovery. The existing fixture writer crash/
early TG/VK progress tests remain. New actual-core-port tests exercise the live
reconcile code and immutable bindings, not only FixtureDriver. Full new-driver
MCP/terminal-resolution and positive publish/edit/delete/media/scheduling replay
remain unfinished; these counts must not be called L01–L16 completion.

Verification invocation notes: do not overlap the standalone browser suite,
archived-core browser suite and live browser on this constrained host. The first
combined run had 132 passes and four failures (one first-event timeout and three
bounded observation failures); all nine affected/adjacent cases passed unchanged
when run serially. The new two-navigation/four-copy recovery tests now use the
normal 10-second driver budget instead of inheriting the old single-navigation
fixture's 2 seconds (one passing serial recovery took 1.85 seconds). A dedicated
short-budget case still proves deadline refusal/quarantine retention. The core
first-event deadline remains **5 seconds**, unchanged. Timeout diagnostics are
sanitized; no retries or relaxed content/reference assertions were introduced.

Reproduce this checkpoint (run browser suites serially):

```sh
PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright artifacts/max-venv/bin/python -m pytest tests/adapters/max tests/browser/max -q -ra
python3 tests/adapters/max/assemble_core.py --archive artifacts/codex/max-core-integration-20260905/vibepublish-native-visual-20260905.zip --output artifacts/codex/max-recovery-20260905/fresh-core
# From that NEW assembled directory, using the existing core virtualenv:
PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright VIBEPUBLISH_MAX_CORE_REQUIRED=1 /home/dev/projects/vibepublish-max-web/artifacts/core-venv/bin/python -m pytest tests/adapters/max tests/browser/max --asyncio-mode=auto -q -ra
```

The assembly verifier checks all 103 original source hashes and cumulative patch
hash against the retained 875577-byte ZIP. Only MAX-owned files are overlaid; the
original port is still `4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`.
No partial remote core, surrogate port, archived core payload push or alternate
route around core protection was used. Final counts/SHA/completed CI and core
coordination are recorded on PR #2.
