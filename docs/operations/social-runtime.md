# VibePublish runtime and delivery status — 2026-09-05

Status: **Not confirmed by user / partial remote delivery**. Keep PR #1 draft.
The checkout lacks three implementation modules and is not a runnable release.
No merge, deployment, live provider or imagegen capability is claimed.

## Source facts, not conversation summaries

Existing branch: `work/vibepublish-core-20260904`, PR #1.
The previous ChatGPT final answer saying no new commits were made after
`c1d0cede` was incorrect. Fresh GitHub reads confirm these five source commits:

| Commit | Preserved archive package |
|---|---|
| `2af860c7de1988dff52a0718bec63cb231ab4e1e` | Typed image executor interface, importer, SVG compositor |
| `7d281dcfb5c43a970927cdfb26fb069447c79fc3` | Emoji palette/selector, VisualService, fake provider and storage/SDK tests |
| `6625766ca7be199226c4f4eaf11097f310aa521e` | Contract and skill 1.5 plus synchronized contract tests |
| `530f9c9aac92927761c915b9a32cd6ac1d0c20d3` | Emoji/native-adapter/transport-double/SDK regression suites |
| `18152e5d7bbc5ebe2d5e04006b0563ab8de9fb2e` | Remaining runtime/MCP/visual/process tests and helpers |

They add 30 unchanged archive files beyond the earlier 26-path source delivery.
The actual source tree is `ad82a3162d15f918e8e05d94a866855aa7633125`.
The downloaded CI artifact `9967172962`, SHA-256
`14b21924768558fd78096a4b06e4db381e9f53343ee2e25f887e346e4552a343`, independently
reconstructed that exact tree. At this readback, 114 of the 133 archived files
matched byte-for-byte; 16 documentation files differed and three runtime files
were absent. The old statement that 48 paths remained was stale.

`76ad2c554fe5866ddd23f79154095d281e099154` then attached ten documentation changes
from the previously accepted tree `1f36d7259bf52d2ca53f54e4bffbee071a103d91`.
That exact tree was successfully read, committed and referenced. Its source,
contracts, tests, dependencies and workflow subtrees equal `18152e5d`; only README
and docs changed. Its actual CI source artifact `9968037869`, SHA-256
`a7af78a1bbe94ba9f450cb4a75889dc04a9d797035f3c75461c2d5dbea14e10c`, reproduced the
same tree. This continuation also preserves the two older archive handoffs as
explicit historical documents, restores the complete visual feature description,
and updates the active handoff/CHANGELOG. Runtime bytes are not reimplemented.

## Three remaining modules

| Path | Remote delivery |
|---|---|
| `adapters/vk.py` | Absent; earlier explicit request-safety-evaluation block |
| `social_operations/rich_text.py` | Absent; earlier explicit request-safety-evaluation block |
| `adapters/codex_imagegen.py` | Absent; earlier explicit request-safety-evaluation block |

Earlier source calls returned: «Этот вызов инструмента был заблокирован OpenAI,
поскольку мы не смогли определить статус безопасности запроса.» The exact cause
was not disclosed. No such call is newly claimed in this documentation-recovery
turn, and none of these three payloads was resent through a different route,
encoding, split file, CI, another agent or MAX. A failed object lookup/422 is a
separate technical error; it is not a missing schema or GitHub permission denial.
The recovered tree above contains no denied module. Access to independent writes
works; that does not authorize bypassing a denied operation. See the existing
[delivery proof rule](repository-workflow.md#proof-of-github-delivery).

## Verification performed in this recovery

Complete input archive: `vibepublish-sdk-locked-20260905.zip`, 1,474,253 bytes,
SHA-256 `179b101877e10c8d37606a4156a4de35e19cda6f127a26181553537623a5c40c`.
All 203 payload hashes and 133 source files were checked again. Archived LOCAL
HEAD `8dcc771848051dab8b9bc7ae51f92a9757dfa7ef`, tree
`c0321a0823ae2373ed2ea51d8740d0da58cbb7bb`, is not the partial remote tree.

A new empty Python 3.13.5 venv installed the 70 locked dependency wheels with
`--no-index --only-binary=:all: --require-hashes`; `pip check` passed. No system-site
Python packages. App installed with `--no-deps --no-build-isolation`.

- `pytest tests/contracts tests/inspection tests/verification tests/runtime/test_storage.py -q`:
  **69 passed + 199 subtests passed**, no failures/skips, 1.31 seconds.
- Standalone real Telethon 1.44 SDK verifier: 14 request kinds, no provider RPC.
- Compilation: passed; syntax success is not import/integration success.
- Full `pytest tests --collect-only -q`: **10 collection errors** caused by
  missing production imports; 111 tests collected, exit 2. No full-suite pass.
- `scripts/verify/telegram_sdk.py`: fails importing `social_operations.rich_text`,
  exit 1. The mandatory core-aware gate remains unchanged.

[Hosted run 33961328151](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/33961328151)
for `76ad2c55` completed with failure. It is not replaced by an older green seed
run. The final PR receipt records the final documentation commit and its CI.
The earlier 327 tests + 199 subtests belong to the complete archived source;
those historical passes are not claimed for this incomplete checkout.

## Preserved behavior and remaining release gates

One SQLite/WAL/FULL application serves HTTP and MCP, eight tools, contract/skill
1.5 and migration 3. Core owns revocable bindings, immutable requests/plans,
idempotency, authority, connection locks, durable dispatch/fencing, private
assets and per-child progress. Native schedules are submitted immediately to the
provider; there is no publication timer. Recovery observes without resubmitting.
Partner reads stay inside active publishing destinations, including other
editors' provider-visible posts/queue, not private drafts/assets. Exact item CAS
and ordered provider-media bindings never claim transcoded-byte equality.

The [emoji workflow](../features/social-operations/telegram-custom-emoji-v1.md)
preserves private numbered previews, exact ordered/repeated parts, immutable
aliases/rules, approved fallback and frozen pre-send entities. Its missing
rich-text compiler prevents end-to-end execution. [VisualService](../features/social-visuals/README.md)
preserves a frozen budget, verified job-scoped artifacts, deterministic editorial
copy, private lineage, candidate hashes/feedback and one parent continuation.
Standalone selection cannot publish; preview still needs approval. Synthetic
images cannot enter native publication. The [Codex process executor](devcoveer-imagegen.md)
exists in the full archive, not in this branch. Actual installed CLI/skill and
image-only controls on DevCoveer remain unverified. An operator boolean or
scripted CLI test is not tool isolation or live image-generation evidence.

For a complete source checkout: install requirements.lock, install the app without
new dependency resolution, install Chromium prerequisites, run the core SDK gate
and all tests. Linux/Python 3.12+, fcntl, libcairo2 and trusted DejaVu fonts are
required; font files are not redistributed. Owner CLI manages explicit bindings
and service tokens. Defaults remain unavailable; fake/native modes cannot mix.
No EventsBot session, credential, provider/model call or deployment occurred.

Public OAuth/TLS/onboarding, URL/ticket asset ingress, recovery UI,
retention/history pagination, owner discovery/live analytics, video/stories,
full mention/rich coverage and unproved native capabilities remain separate
release gates. MAX PR #2 was read at `78d8a53954a97a0fb18c4a929bc3a66b2263325d`;
no MAX code, shared port, task or combined live test was changed here. Complete
source delivery, full hosted runtime tests, installed host controls, permitted
live-provider tests and owner acceptance remain distinct requirements.
