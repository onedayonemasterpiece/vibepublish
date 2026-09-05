# MAX Web — offline driver checkpoint, 2026-09-05

Status: **Not confirmed by user / Partial**. This is NOT a live MAX adapter
release. Canonical requirements remain the two MAX handoffs (September 4 and 5),
with September 5 taking precedence. No live reads, writes, canaries, imagegen,
EventsBot credentials or deployment are authorized by this checkpoint.

## Delivery boundary

Branch: `work/vibepublish-max-web-20260904`, created from fresh `origin/main`
`1ceb1cee2acd867c88f6e94a2815e78e816374fa`; no prior MAX branch/PR existed.
Fresh-read core branch/PR #1 HEAD:
`49efec417e0605b95979ed3a3eebd1c0eb3bade8` (comments empty at inspection).
The core PR explicitly says the full runtime is NOT remotely stored.

**Blocker:** `vibepublish-native-visual-20260905.zip` was not delivered into this
execution environment. Exact-name filesystem search found no file; a repeated
attachment or absolute path was requested. The expected LOCAL core HEAD
`870e2a4304c57ef5dd7152de63df1db6431a942b` is reported by the handoff/PR, NOT
verified here. MANIFEST, all hashes and actual archived worker/port remain
unverified. Expected port SHA-256:
`4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`.
No archive, old seed port, second ProviderRequest/Observation/Hooks contract,
core runtime, Telegram/VK provider, MCP server or VisualService was copied into
this MAX delta.

The independent `adapters/max/driver.py` is explicitly `FixtureDriver`: a bounded
UI state machine using a **synthetic** DOM. It accepts only its configured
127.0.0.1 HTTP fixture origin. These selectors have never been observed in live
MAX. There is deliberately no production factory or connection registration.
The immutable ProviderAdapter bridge must be implemented against the actual
archive, not guessed from the older remote seed. The `max` package is loaded in the tests with `importlib.import_module('adapters.max.driver')`.

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

Local validation: **37 MAX tests passed** (3 profile unit/process tests and
34 real-browser tests), plus **22 existing contract tests passed**; no skips.
Compilation and `git diff --check` passed. An intermediate exact-label selector
regression was diagnosed on the synthetic DOM and fixed; short test-only global
timeouts were removed so fault injections reach the intended dispatch boundary.
These final results supersede the preserved failed intermediate logs.

Local report/evidence: `artifacts/codex/max-web-20260905/` (not committed).
Local environment: Python 3.12.3, Chromium 145.0.7632.6.
Version pins: Playwright 1.58.0, pytest 8.4.2, pytest-asyncio 1.3.0.
Record actual Python/Chromium versions and exact remote PR/CI SHA in the delivery
report; do not infer success from a workflow file.

| Requirement | Status in this checkpoint |
|---|---|
| M01/M02/M03/M04/M05 | Synthetic account/identity/virtualization/rerender/upload-order tests; live unverified |
| M06 | Delayed image processing covered; video explicitly unsupported |
| M07 | Synthetic expired/wrong account rejection; real QR/CAPTCHA human flow unverified |
| M08 | Pre-marker callback failure -> zero submit; full core crash/replay not run |
| M09 | Real SIGKILL of worker + Chromium; independent provider state survives; restarted read-only reconcile, one effect |
| M10 | Old and duplicate candidates unknown; text-only authorship deliberately unresolved |
| M11 | Real competing processes, crash quarantine, same-process lane and event-loop independence |
| M12 | Queue/edit/reschedule covered; cancel effect observed but success not asserted |
| Additional safety | Callback failure, permissions/account/target/composer change, lead-time expiry, external CAS, foreign channel/assets |
| Canonical port + real MCP ClientSession/TG/VK integration | **Blocked: archive missing**; no mocks presented as proof |
| Local assembled core tree | **Not run**; no MANIFEST/hash verification possible |
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

**One next package:** provide and verify the ZIP manifest/source hashes, assemble
an isolated local core tree, implement only the canonical MAX port bridge and
real ClientSession/worker integration tests (including first TG/VK status while
MAX waits and durable dispatch crash recovery). Preserve the MAX-only PR; do not
push the core archive as a workaround. Live locator/canary work remains gated.
