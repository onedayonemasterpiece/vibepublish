# VibePublish runtime and delivery status — 2026-09-05

Status: **Not confirmed by user / partial acceptance**. Keep release/full CI unaccepted.

## Current isolated acceptance

The [canonical DevCoveer report](devcoveer-acceptance-20260905.md) records the
new adapter, dedicated Telegram worker, actual native lifecycle/readback, public
MCP, 375 passing local tests and remaining VK/imagegen/ingress durability gaps.
This acceptance branch supersedes missing-module and no-live-call statements
below; those describe the earlier remote core delivery only. Main/MAX unchanged.

## Historical remote-core delivery (not current acceptance state)

## Current source

Branch: `work/vibepublish-core-20260904`.
Source commit: **`ae73b259ddf60c80875c285d3e5c9d51723ce3f0`**.
Tree: **`804d922019fc4ec417f982ace70ef3342f8d2eb8`**.
This adds `social_operations/rich_text.py` and `adapters/vk.py` to `b84c2082`.
Both complete files were accepted by the normal GitHub tree action and copied
without modification from the verified archive. Commit/ref readback succeeded;
independent local reconstruction matches the exact accepted tree. Existing core,
contracts, tests, dependency pins and mandatory CI were not rewritten.

**132 of the archive's 133 source paths are present.** The only missing file is
`adapters/codex_imagegen.py`. Its full-file write in this continuation returned:

> Этот вызов инструмента был заблокирован OpenAI, поскольку мы не смогли определить статус безопасности запроса.

No new tree was returned for that request. It was not retried via another route,
encoding, partial file, CI, MAX or an agent. Successful Telegram/VK writes do not
imply that the Codex module was delivered. Older three-module and 48-path counts
are superseded by this section. Prior source history is preserved in Git.

## Checks on the delivered source

A new empty Python 3.13.5 virtualenv installed all 70 locked dependency wheels
using `--no-index --only-binary=:all: --require-hashes`; `pip check` passed before
and after application installation without dependency resolution. No system-site
Python packages were reused. OS Cairo/fonts/Chromium are available, not a fresh
OS-image claim. The local checkout deliberately does not contain the undelivered
Codex module during these checks.

- Core-aware SDK gate: **PASS**, real Telethon 1.44.0; all 14 request constructors
  roundtrip through the actual compiler, including three custom entities. No RPC.
- Strict full test collection: **296 collected, one import error** in
  `tests/visuals/test_codex_imagegen.py`; missing `adapters.codex_imagegen`.
- Diagnostic full invocation with `--continue-on-collection-errors`:
  **296 passed, one collection error, 199 subtests passed**, 23.93 seconds,
  exit **1**. This includes Telegram emoji/native SDK, VK, MCP/HTTP/worker,
  browser preview and shared visual tests. It is explicitly NOT a green full
  suite: 31 archived Codex-process tests cannot collect without their module.
- Hosted CI for the source commit: run **33964190704**. Read its actual final
  result in PR #1; a pending run or the diagnostic count above is not a PASS.

The workflow and tests remain unchanged; no import skips, stubs or exclusions
were introduced. The old 327 + 199 full result belongs to the complete archived
source and is not claimed for this partial remote checkout.

## Preserved requirements and remaining acceptance

One SQLite/WAL/FULL application serves HTTP and MCP, with eight tools,
contract/skill 1.5 and migration 3. Core owns current authorization, immutable
requests/plans, idempotency, per-connection locks, durable dispatch/fencing,
private assets and per-child progress. Native schedules are submitted to the
provider immediately, never held by a local publication timer. Uncertain effects
are observed without resubmission; partial provider successes are preserved.

Partner reads cover provider-visible content and queues only in active publishing
bindings, not another principal's drafts/assets. Exact item CAS and ordered
provider-media bindings do not assert equality of transcoded bytes. The Telegram
compiler now accompanies the existing catalogs, numbered visual picker,
ordered/repeated emoji chains, immutable aliases/rules and semantic readback.
[Emoji requirements](../features/social-operations/telegram-custom-emoji-v1.md)
remain binding; their earlier delivery banner is superseded by this status.

[VisualService](../features/social-visuals/README.md), importer and compositor
retain immutable budgets, exact editorial copy, private lineage and one parent
continuation. Standalone selection does not publish; preview needs approval;
synthetic images cannot enter native publication. Actual image-only Codex
CLI/skill/controls **on DevCoveer**, real artifacts and cost limits remain
unverified separately from the missing source file. No guessed OpenCode,
personal-PC, Google or API-key fallback is substituted.

No live provider/model call, session use, deployment, merge or MAX write occurred.
MAX was fresh-read at `9d3e9c37ea2111eaeee30e9ae386d6225438aa3a`; its independent
live test is unresolved and is not accepted or repeated here. Public OAuth/TLS,
onboarding, asset URL/ticket ingress, recovery UI, retention/history pagination,
owner discovery/live analytics, video/stories, full rich/mention coverage and
unproved native capabilities remain the existing release gates.

## Source preservation and next step

Complete reference archive: `vibepublish-sdk-locked-20260905.zip`, 1,474,253 bytes,
SHA-256 `179b101877e10c8d37606a4156a4de35e19cda6f127a26181553537623a5c40c`.
All 203 payload hashes and 133 source hashes were checked. Do not overwrite newer
branch docs with the archive or label its local commit as remotely delivered.

The remaining delivery step is the existing `adapters/codex_imagegen.py`, not a
rewrite of Telegram/VK or a new MAX task. Keep the current request-safety outcome
and [delivery proof rule](repository-workflow.md#proof-of-github-delivery).
Full remote CI, actual DevCoveer host evidence and authorized live/owner acceptance
remain separate requirements.

### MAX raster emoji font evidence (2026-09-08)

Observed MAX Web renders Unicode emoji as neutral non-editable raster decorators.
Font weight/slant cannot be inferred from a boundary emoji. `max_entities`
therefore excludes Unicode emoji-presentation graphemes from bold/italic spans
and joins only adjacent same-style text spans. Exact text and link spans/URLs
are unchanged. The immutable caller intent is retained; MAX verification uses
this visual semantic projection for both expected and observed entities.
Telegram/VK and non-font entity validation are unchanged. `regex` grapheme and
Unicode properties follow [UTS #51](https://unicode.org/reports/tr51/); plain
digits, text-presentation selectors and ordinary copyright symbols are not
neutralized. Malformed spans still fail before projection.

### Unreachable-input compensation, not fabricated publication

The additive trusted `NoEffectProof` port value is an adapter control-flow proof,
not a conclusion from an empty feed or a model answer. Core verifies its binding
to the immutable original checkpoint, current actor/binding/plan/fence and a
zero-input proof before recording **cancelled / observed not_attempted**. No
native item is created, no successful publication is claimed, and historical
`dispatched=1` is preserved. The original command remains cancelled under all
idempotency keys; a new, different intent is not an automatic effect retry.

The existing durable finalization outbox releases only the matching quarantine
**after** that outcome commits; a failed release is retried across worker restart.
Public delivery results may expose the additive compensation enum
`intent_cancelled_without_effect` and its reason. Absence-only, nonzero-click and
wrong-checkpoint proofs remain unresolved and cannot release the connection.
Read-only reconciliation has a bounded 90-second observation window (separate
from the expired original effect deadline), to allow repeated native UI checks.

Finalization receives the already committed observation from the recovery journal
without overwriting its immutable original checkpoint. Thus a native ID first
learned during read-only recovery can be validated during post-commit release;
no caller-supplied reference or fake scheduled URL is required.

MAX Web may replace a native queued item ID when changing its native time.
`Observation.replacement` carries typed `NativeReplacement` evidence binding the
old fingerprint/ID to the new ID. Core accepts this only for MAX Web scheduled
reschedule, with exact target/content, requested time and unchanged downloaded
media. Other providers/actions and missing/incorrect proofs retain strict native
identity checks. Download binding accepts the same explicit proof; it does not
pretend the old and new native IDs are equal. Logical publication/revision and
original attempt remain unchanged. Post-commit finalization receives the durable
replacement observation, including across restart; it never repeats Save.

Cancelled/deleted receipts omit pending-queue navigation/requested-time fields,
including projection of older committed results retaining a native scheduled
snapshot. That historical snapshot remains immutable; status serialization does
not manufacture a new schedule or require a repeated deletion. The regression
covers both fresh cancellation and legacy nullable requested-time results.

### MAX engagement core contract (implementation in progress)

Reply/react admission resolves an existing authorized published `item_ref`, freezes
its native subject, and uses the same operation/attempt/worker pipeline. It requires
explicit `reply`/`react` binding rights; existing bindings do not silently acquire
them. Owner CLI `grant-rights --binding-id … --right reply --right react` adds rights
without removing prior grants, changing target/account identity, invalidating old
binding epochs, or altering any attempt/quarantine. Revocation remains separate.

Reply verification requires the exact native subject relationship and new native
item plus unchanged requested content. Reaction verification requires explicit
observed own-reaction state (not another user's count or missing metadata), exact
subject and requested add/remove outcome. `reacted` and reaction result fields are
additive receipt metadata. Other provider adapters are not enabled implicitly.
MAX forwarding from a bound read ref preserves its verified native permalink,
subject content/entities/download evidence and native attribution. External MAX
URL ingress remains disabled; no URL becomes a grant. These core tests do not
claim live MAX social acceptance; the real driver qualification is in PR #2.

Native MAX forwarded downloads may bind to the already authorized, frozen source
subject without re-uploading media. This requires exact provider/source URL/chat/
item coordinates and matching downloaded bytes; it does not accept arbitrary
provider observations as upload evidence. Core still separately requires native
forward-origin proof and exact source body/entities/media before committing the
result. Existing publish/edit bindings and other providers remain unchanged.

MAX `read(kind=reactions, item_ref=…)` uses the same authorized exact-reference
read worker. It returns explicitly observed **own** reactions, including `[]` for
proved removal; it does not enumerate other participants. Missing metadata,
multiple items or a different native ID cannot become verified empty reactions.
Other providers and non-published namespaces are not implicitly enabled.

Native `max_web` reads now receive a bounded 90-second browser budget (never past
an operation's deadline), matching mutation/recovery's existing upper bound.
The live exact-own-reaction read reproduced the old 30-second cutoff. API/fake
provider reads retain 30 seconds. Expiry reports `provider_read_deadline` with
refresh, not a generic worker failure, and authorizes no mutation or resend.

## Telegram P0 Stage B–G local integration — 2026-09-12

Status: `Not confirmed by user`; **local integration, not deployed completion**.
The exact remote source `cee52feb875ca0e7d6a64c00056bd3e9abb8974e` was verified
by `git ls-remote` and fetched into a temporary inspection repository under
`artifacts/telegram-p0-stage-b/`. Normal acceptance fetch failed because the
linked checkout's actual Git metadata is outside the permitted writable roots:
`/home/dev/projects/vibepublish/.git/worktrees/vibepublish-acceptance-20260905`.
The acceptance checkout remains on `converge/core-max-integration-20260910`,
HEAD `83ffabc2a4d90bf801efb6b30c529ebacfa6e478`, with scoped uncommitted integration.
No source correction was needed; source branch/PR #1 were not changed or pushed.

Semantic integration uses the eleven-file `25d7207` delta from common ancestor
`87be8fc`. Three-way resolution preserves the acceptance basic-chat gate and
prompt-first visual documentation. The former provider test that blanket-denied
megagroups now checks native permissions; ChatEmpty/ChatForbidden remain denied.
Additional acceptance tests cancel a worker after its durable response checkpoint,
reopen the SQLite fixture, replace the worker/adapter and verify single-effect
recovery for text/photo/document plus keyed replay.

Existing venv only: `.venv/bin/python`, Python 3.12.3. No dependency installation,
upgrade or venv recreation. Preflight's CairoSVG import issue, missing pip and
regex lock drift did not block the requested suites and were not repaired.
Initial providers: 169 passed, 1 stale expectation failed. Updated providers:
170 passed. Initial required contracts/runtime/sdk/verification group: 206 passed,
202 subtests passed, 2 warnings. Targeted topics/media/restart: 15 passed.
Final required group rerun: 209 passed, 202 subtests passed, 2 warnings. All
final requested runs have zero failures and zero skips.
No real Telegram calls were made by these tests.

The base unit's 18765 is overridden by existing `street-story-runtime.conf` to
18766. `ss` subsequently observed LISTEN `127.0.0.1:18766` (PID not exposed).
The authorized first deployment operation, stopping the existing worker, failed:
`Failed to connect to bus: No data available`. The sequence was not continued out
of order. ActiveState/SubState/MainPID/NRestarts and actual process ownership
remain unavailable. No alternate service/runtime or host-control mechanism was
created; no existing approved project control wrapper was found.

Existing public HTTPS endpoint checks succeeded with TLS verification enabled:
anonymous MCP 401; both OAuth discovery documents 200; authenticated initialize
200 and initialized notification 202; exactly the eight expected tools; readable
nonempty skill; private asset template listed. An existing owner's private asset
was read through MCP (200, 247 bytes, exact stored SHA-256/MIME match). Credentials
were consumed in memory from the existing owner-token store and never printed.
These prove the existing public endpoint, NOT activation of this local integration.
A follow-up public tools-schema check confirms `publish.thread_ref` is absent: the
new Telegram P0 contract is not active on that endpoint. Deployed SHA is not exposed.

The second read-only ledger inspection still found zero Telegram destinations
matching peer -1004379835477. Binding scope is peer-level, without a topic column.
Because deployment was blocked this is not an authoritative post-deployment gate;
no target reads/sends, grants or binding changes were attempted. Topic 3 live
acceptance remains blocked by missing pre-existing binding and deployment access.
Runtime databases were not checkpointed/mutated: service stop was not established.
No unrelated cleanup, Imagegen work, Fly action or new runtime was performed.
