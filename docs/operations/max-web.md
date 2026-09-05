# MAX Web — offline shared-port integration, 2026-09-05

Status: **Not confirmed by user / Partial**. This is NOT a live MAX adapter
release. Canonical requirements remain the two MAX handoffs (September 4 and 5),
with September 5 taking precedence. No live reads, writes, canaries, imagegen,
EventsBot credentials or deployment are authorized by this checkpoint.

## Delivery boundary

Branch: `work/vibepublish-max-web-20260904`, created from fresh `origin/main`
`1ceb1cee2acd867c88f6e94a2815e78e816374fa`; no prior MAX branch/PR existed.
Previous MAX checkpoint: `d0bceb2efd1ab2da83e6553a61f1a33b31a7b755`, same
[PR #2](https://github.com/onedayonemasterpiece/vibepublish/pull/2).
Fresh-read core PR #1 HEAD: `6ffeb4270ee01f7fe23463dfecef0b1bdb033883`.
Its newest change is documentation-only; full core still is not remote.

**Archive blocker resolved.** Actual bytes were found at the owner-specified
EventsBot `docs/reference/` path, verified and moved (not copied/committed) to
`artifacts/codex/max-core-integration-20260905/vibepublish-native-visual-20260905.zip`
in this MAX worktree. Retained one ZIP, 875577 bytes; SHA-256
`5651e09a046806b0bfd1fcfb7a92998c22fd9e1c902e1d7f28b53db5fdbe1933`.
All **103 source hashes**, **176 payload hashes**, and cumulative patch SHA-256
`0b5ce0ca814e97e89e33714748a25a9f3a47e450bbcd0c33d566f1d7e327bff6` match MANIFEST.
The Git bundle verifies LOCAL core HEAD
`870e2a4304c57ef5dd7152de63df1db6431a942b`, tree
`a66651154eac632b1e45765b52d2dff87413cc74`; applying the cumulative patch to its
base in an isolated local Git object store reproduces that exact tree.
Port last-change commit: `25de851b911d02fc9ece2a7e193743758bfa48c1`;
SHA-256 `4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`.
No archive/core source or Git objects are pushed as part of MAX delivery.

`adapters/max/bridge.py:MaxAdapter` now implements the **actual**
`ProviderAdapter.inspect/prepare/execute/read/reconcile` boundary. It imports
canonical request/result/callback types and existing `adapters.native` helpers;
there is no copied port, authorization, ledger, idempotency or dispatch code.
Core owns the request, permissions, fence and durable marker. Port is unchanged;
[coordination with core](https://github.com/onedayonemasterpiece/vibepublish/pull/1#issuecomment-5550042852)
records compatibility with the separate future additive rich-entity/emoji work.
MAX rejects non-plain content explicitly instead of dropping entities.

**Not a production MAX factory.** Trusted test wiring must inject the existing
`FixtureDriver` with a connection ID, fake account and empty secret reference.
The synthetic DOM/127.0.0.1 guard is unchanged. No real profile is selected and no
live locator set is invented. The bridge converts `feed` to core `published`,
binds ordered upload IDs to validated input-asset hashes, returns real fixture
identities/time, and never invents a permalink or transcoded-byte equality.
Read-only external queue items have provider IDs but no invented input hashes.

Driver progress `running` is translated to core `started`: genuine Store.event
validation exposed this mismatch during integration. Every event still awaits
core persistence. Protected checkpoints keep version/attempt/plan/target plus
the original driver baseline even after observation, so a crash before
Worker.finish_child cannot destroy reconciliation evidence. Unknown results
never enter execute again. Only matching, durably observed attempts clear the
profile quarantine during recovery. Observation remains allowed after command
deadline expiry; expiry never authorizes a new effect.

## Safety and observations

- Exact target allowlist and account identity, checked before navigation, on
  each read page, after callbacks, and before final submit. No account-wide
  search, other-chat read, asset-path opening or private asset download.
- A Linux nonblocking `flock` owns the profile across Chromium launch/close.
  The same process also rejects overlapping driver calls. No lease takeover.
  Protected directory/lock permissions, symlinks and hardlinked lock rejection.
- A fsynced `.vibepublish-uncertain` safety fuse is armed before `before_effect`.
  It contains attempt/digest only, no content or credentials. This is not an
  operation journal or replacement dispatch ledger. Core still must persist
  its dispatch marker and authorize the exact attempt in `before_effect`.
- All progress/checkpoint callbacks are awaited. Refusal or DB failure causes
  zero submit clicks. A failure after arming is conservatively unknown, even
  when the driver probably never clicked. Every fresh mutation on that profile
  remains blocked across process death and new operation IDs.
- Reconciliation is read-only and does not clear quarantine. Only trusted core
  recovery may call `resolve_observed` after exact observation is durably saved.
  The normal success path saves MAX_OBSERVED before removing the fuse. Never
  manually delete it merely to make another send work.
- Native time requires an offset and at least 90 seconds lead, rechecked after
  callbacks. No scheduling timer or conversion to now. Synthetic reschedule
  edits the same item; edit cannot silently change time. Reschedule of media
  items is currently rejected because media preservation is unverified; it never
  clears existing images or changes text as a side effect.
- Baseline identities, exact scope, text, native time and ordered provider media
  identities are checked from saved queue/feed items, not composer/toast.
  Source bytes are never claimed equal to transcoded provider images. Input
  payload validation in the real service remains a core responsibility.
- Text-only creation lacks attribution evidence in this fixture: even one new
  matching post remains `outcome_unknown`; old/multiple matches never prove
  success. Deletion/queue absence alone also remains unknown. No repost retry.
- CAS is a live pre-effect comparison, **not atomic provider CAS**. A remote
  editor can still change an item between the last read and UI submit; live
  capability activation must account for that limitation.
- Internal prepared checkpoints include channel-visible content and identities;
  trusted core must store them as protected evidence, never ordinary logs or
  model-facing raw JSON. Exceptions are sanitized; screenshots are opt-in.

## Capability matrix

| Capability | Synthetic browser evidence | Live MAX |
|---|---|---|
| Exact account/target, scoped queue incl. other editors | Covered | Not verified |
| Immediate text | Submit once; attribution remains unknown | Not verified |
| Text + ordered images | Saved-item provider identity/order readback | Not verified |
| Native schedule | Stored queue time/media; no local timer | Not verified |
| Edit/reschedule | In-place identity, pre-effect CAS and readback | Not verified |
| Cancel/delete | Submit path only; absence cannot prove success | Not verified |
| Video, rich content, stories | Explicit unsupported; no silent downgrade | Not verified |
| Native forward, discovery, analytics | Explicit unsupported; no copy substitute | Not verified |

## Reproduce offline evidence

```bash
python3 -m venv artifacts/max-venv
artifacts/max-venv/bin/pip install -r adapters/max/requirements-test.txt
artifacts/max-venv/bin/python -m playwright install --with-deps chromium
artifacts/max-venv/bin/python -m pytest tests/adapters/max tests/browser/max -q
```

Linux required for flock/process-group tests. Browser fixture server binds
127.0.0.1 only; every test browser aborts requests outside that exact origin.
No social credentials are read. Tests use fresh temporary profiles, never
personal/EventsBot browser sessions. The one canonical CI path
`.github/workflows/ci.yml` is reused from the core branch, preserving its contract,
inventory and source-artifact steps. MAX tests are unconditional; absent core
source/inventory steps are explicitly conditional on this main-based MAX branch.
A green MAX CI is NOT full-runtime CI.

## Actual-core integration reproduction and evidence

The local assembler verifies the immutable owner ZIP, writes only to a **new**
`artifacts/` directory, overlays MAX-owned paths, then rechecks every archived
source hash. It never writes core into the MAX checkout or pushes it.

```bash
ROOT="$PWD"
ART=artifacts/codex/max-core-integration-20260905
TREE="$ART/assembled" # must not already exist; choose a new artifacts path
python3 tests/adapters/max/assemble_core.py \
  --archive "$ART/vibepublish-native-visual-20260905.zip" --output "$TREE"
python3 -m venv artifacts/core-venv
artifacts/core-venv/bin/pip install -r "$TREE/requirements.in" playwright==1.58.0
(cd "$TREE" && VIBEPUBLISH_MAX_CORE_REQUIRED=1 "$ROOT/artifacts/core-venv/bin/python" \
  -m pytest tests/adapters/max tests/browser/max --asyncio-mode=auto -q -ra)
(cd "$TREE" && "$ROOT/artifacts/core-venv/bin/python" -m pytest tests/contracts -q)
```

The archived pyproject uses strict asyncio mode; MAX's original standalone suite
uses auto mode. The explicit CLI option preserves all original 37 async tests
without rewriting either core configuration or their assertions. New core tests
also have explicit asyncio marks. `VIBEPUBLISH_MAX_CORE_REQUIRED=1` makes missing
core a hard import failure, not a silent skip. No fake replacement port exists.

Evidence is split deliberately:
- **MAX-only checkout / remote CI:** original 37 tests; the two actual-core test
  modules explicitly skip with “Full owner core archive required”. Bridge syntax
  compiles, but remote seed-only CI does NOT execute its runtime integration.
- **LOCAL assembled tree:** original 37 plus 18 actual-port/core tests. Genuine
  MCP ClientSession/HTTP server, original Worker/SQLite, archived TG/VK
  FakeProvider instances and actual Chromium MAX fixture. No SDK/page mock is
  passed off as the MCP path. New tests cover early first-event long-poll, both
  now and native schedule with two ordered images, independent pre-effect SQL
  marker observation, real process-group SIGKILL, restart/reconcile, partial
  success preservation, callback/refusal/revocation and uncertain marker cases.
  Native queue pagination/exact external item reads also pass through MCP/worker.
- The crash test expires the **existing core claim** via explicit test SQL after
  killing the process. It does not implement adapter lease takeover; dispatched
  remains 1. Original operation/attempts and finished TG/VK children survive;
  duplicate click and a new intent cannot bypass uncertainty.
- **Live read/write/canary/deployment:** not run, no authorized profile/destination.

Final local results: **55 MAX tests passed, 0 skipped** (37 preserved + 18 new)
in the assembled tree; **24 archived contract tests + 193 subtests passed**.
Standalone MAX checkout: **37 passed, 2 core-module skips** (archive deliberately
absent there). Compilation and diff checks passed. After tests, all 103 archived
source hashes were rechecked unchanged. Intermediate failure logs remain as
root-cause evidence, not the current verdict.

Actual pass counts/commands and intermediate failed runs are retained under
`artifacts/codex/max-core-integration-20260905/`; the delivery PR records exact
commit, remote blob readback and CI conclusion. This is a fresh requirements.in
integration environment, **not requirements.lock/full-runtime verification**.
Local Python 3.12.3, MCP 1.29.0, Playwright 1.58.0, Chromium 145.0.7632.6;
core-test pytest 9.0.2/pytest-asyncio 1.3.0; standalone MAX pytest 8.4.2.

| Requirement | Status in this checkpoint |
|---|---|
| M01/M02/M03/M04/M05 | Synthetic account/identity/virtualization/rerender/upload-order tests; live unverified |
| M06 | Delayed image processing covered; video explicitly unsupported |
| M07 | Synthetic expired/wrong account rejection; real QR/CAPTCHA human flow unverified |
| M08 | Core callback refusal -> dispatched=0/effects=0; real post-marker crash -> unknown/no retry |
| M09 | Real core worker + Chromium SIGKILL; actual ClientSession status/replay; restart reconciles now/scheduled, one effect |
| M10 | Old and duplicate candidates unknown; text-only authorship deliberately unresolved |
| M11 | Real competing processes, crash quarantine, same-process lane and event-loop independence |
| M12 | Queue/edit/reschedule covered; cancel effect observed but success not asserted |
| Additional safety | Callback failure, permissions/account/target/composer change, lead-time expiry, external CAS, foreign channel/assets |
| Canonical port + real MCP ClientSession/TG/VK integration | Implemented locally with original core and explicitly fake TG/VK providers |
| Local assembled core tree | Verified archive/bundle/patch; all 103 core source files remain unchanged |
| Live read / live write / deployment | **Not run**, no permitted profile/write destination |

Tests intentionally produce unknown outcomes, including deletion, text-only and
callback failures. Their isolated profiles are temporary and are not live
operations needing social cleanup. No social posts were created or deleted.

## Blocked canary procedure — DO NOT RUN now

Requires a NEW explicit live-write authorization, exact dedicated profile/account
reference, and an owner test destination allowlist. An env variable alone is not
consent. Current authorization and allowlist are absent; no executable live
entrypoint is shipped.

After the archived core integration and authorized read-only locator audit:
1. Confirm the exact allowed account/channel and native capabilities; record a
   harmless text/image/time plan and user-approved cleanup action.
2. Submit one native schedule through core, verify the actual queued item, persist
   receipt and remote identity. Do not infer scheduling from a toast.
3. Stop ALL VibePublish processes before due time. An independent authorized
   observer verifies publication by MAX, recording native identity/time.
4. Restart with writes disabled; reconcile that same operation. Prove the effect
   count remains one. Cleanup only if separately authorized; report unknowns.

**Remaining production implementation (separate authorized package):** real MAX
selector/factory implementation backed by explicitly permitted read-only UI
inspection; dependable text-only attribution; native cancel/delete evidence;
media-preserving in-place reschedule. Keep video/rich/stories/native-forward/
discovery/analytics gates explicit. Archive/full core remote delivery and its
locked CI remain core-owned, not a payload to upload through MAX PR #2.
Live canary procedure above stays blocked until new permission and allowlist.
