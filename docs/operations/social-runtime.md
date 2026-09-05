# VibePublish runtime and delivery status — 2026-09-05

Status: **Not confirmed by user / partial remote delivery**. Keep PR #1 draft;
this checkout is not a runnable release. No deployment or live provider/imagegen
capability is claimed. This file supersedes the delivery status in old handoffs.

## Delivered source and the three remaining modules

Existing branch: `work/vibepublish-core-20260904`, PR #1. Main and the independently
owned MAX PR #2 are not modified by this work. The continuation began at remote
`c1d0cede9772164c13458d80370b7cd0cc7d4b1c`, tree
`267bf574600d28b1516aeccac54e5e6edc3b893f`, reconstructed from its actual CI source
artifact. New status documents were preserved rather than overwritten wholesale.

Five source commits transfer **30 unchanged archive files**:

| Commit | Added/restored package |
|---|---|
| `2af860c7de1988dff52a0718bec63cb231ab4e1e` | Typed image executor interface, importer, SVG compositor |
| `7d281dcfb5c43a970927cdfb26fb069447c79fc3` | Emoji palette/selector, VisualService, fake provider and storage/SDK tests |
| `6625766ca7be199226c4f4eaf11097f310aa521e` | Contract and skill 1.5 plus synchronized contract tests |
| `530f9c9aac92927761c915b9a32cd6ac1d0c20d3` | Emoji, native-adapter, transport-double and real-SDK regression suites |
| `18152e5d7bbc5ebe2d5e04006b0563ab8de9fb2e` | Remaining runtime/MCP/visual/process acceptance tests and helpers |

The resulting source tree is `ad82a3162d15f918e8e05d94a866855aa7633125`.
Each accepted tree was independently reconstructed from exact local bytes and
compared by Git tree hash, then committed and referenced without force. Source
and tests are not newly implemented or replaced with simplified substitutes.
Subsequent documentation synchronization does not alter those tested file bytes.

**Only these three implementation modules remain absent:**

- `adapters/vk.py`: earlier explicit request-safety block.
- `social_operations/rich_text.py`: earlier explicit request-safety block.
- `adapters/codex_imagegen.py`: one new blocked request in this continuation.

The new response was:

> Этот вызов инструмента был заблокирован OpenAI, поскольку мы не смогли определить статус безопасности запроса.

The denied Codex request returned no new tree SHA. None of the three denied
payloads was retried, re-encoded, split, substituted, delegated or sent through
another tool, CI, an archive upload or the MAX branch in this continuation.
Other independent source/test writes succeeded. The exact safety-check cause is
unknown; this is not a GitHub 401/403 or proof of permanent read-only access.
Imports and complete execution depend on these missing modules. No stub,
importorskip or relaxed CI check disguises that dependency.

## Current verification, not inherited pass counts

The complete input archive `vibepublish-sdk-locked-20260905.zip` was revalidated:
1,474,253 bytes, SHA-256
`179b101877e10c8d37606a4156a4de35e19cda6f127a26181553537623a5c40c`;
all **203 payload hashes and 133 source files** match. Archived LOCAL HEAD
`8dcc771848051dab8b9bc7ae51f92a9757dfa7ef`, tree
`c0321a0823ae2373ed2ea51d8740d0da58cbb7bb`, is not a remotely delivered full commit.

Current checks use an empty Python 3.13.5 venv, all 70 dependencies installed
from the actual hosted wheelhouse with `--no-index --require-hashes`, followed
by application installation with no dependency resolution. `pip check` passes.
No system-site Python packages were used; this is not a fresh OS image claim.

- Delivered independent contract/inventory/dependency/storage suite:
  **69 tests + 199 subtests passed**. Storage alone: 8 tests + 6 subtests.
- Complete `pytest tests`: **10 collection errors**, before full test execution,
  because required production modules are absent. This is not a runtime pass.
- `scripts/verify/telegram_sdk.py`: fails importing `social_operations.rich_text`.
  The mandatory core-aware SDK gate was retained, not replaced with SDK-only proof.
- Python compilation passes; compilation is syntax evidence, not import or
  provider integration evidence.

[Hosted CI 33958531201](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/33958531201)
for source commit `18152e5d` completed with **failure**. The single existing
workflow includes mandatory core/SDK/full-runtime checks. Current missing source
must fail; an old green seed-only workflow cannot establish complete delivery.
The final PR receipt records the later documentation commit and its exact CI.

The earlier **327 tests + 199 subtests**, real Telethon 1.44 TL roundtrips,
Chromium/MCP/process checks, wheel installation and independent patch replay
belong to the **complete archived source**. Their logs are retained, but they
were not rerun successfully on this partial checkout. Newly stored test files
preserve that regression suite; they are not fresh evidence of live operation.

## Preserved application behavior

One SQLite/WAL/FULL application serves HTTP and real MCP transport. The contract
and canonical skill are 1.5; there remain eight tools. The core owns revocable
bindings, immutable requests/plans, idempotency, current authority, connection
locks, durable dispatch markers, fences, private assets and per-child progress.
The worker submits native schedules immediately; there is no local publication
timer. After an uncertain effect, recovery reads without resubmitting. Partial
success on another provider is retained. These implementation descriptions do
not make the present incomplete checkout executable.

Partner reads stay inside active publishing destinations, including other
editors' visible posts and native queue items; they never grant access to private
drafts or assets. Lifecycle addresses either private publication ID/revision or
an exact scoped item_ref. Native media order/identity, not transcoded-byte equality,
anchors `provider_binding`. External edits invalidate stale snapshot CAS.

The [emoji workflow](../features/social-operations/telegram-custom-emoji-v1.md)
retains private sets and numbered images, exact ordered/repeated parts, immutable
aliases/rules, meaningful approved fallback and frozen pre-send entities. The
selector emits a pending typed command, not an automatic write. Revocation,
expiry, catalog revisions, UTF-16 spans, native IDs and readback are enforced in
the complete snapshot. The missing rich-text module prevents the end-to-end path.

[VisualService](../features/social-visuals/README.md) retains one immutable budget,
job-scoped verified artifacts, exact editorial copy, candidate hashes, private
lineage, feedback and one parent continuation. Standalone choice never publishes;
preview still needs approval. Fake images cannot enter native publication.
The [local Codex executor](devcoveer-imagegen.md) is implemented in the archive but
not delivered as a module. Its installed CLI/skill and actual image-only controls
**on DevCoveer** remain unverified. No personal-PC/OpenCode/Google/API-key fallback
or model task was used. An operator boolean is not evidence of tool isolation.

## Setup and retained release gates

For a **complete** source checkout, the verification sequence is:

```sh
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m playwright install --with-deps chromium
python scripts/verify/telegram_sdk.py
python -m pytest tests -q
```

Linux/Python 3.12+, fcntl, libcairo2 and trusted DejaVu fonts are required. Font
files are not distributed. `init`, `principal`, `connection`, `bind`, `image`,
`revoke` and `backup` are owner CLI actions, not model-facing account management.
Default providers are unavailable; explicit fake/native modes cannot be mixed.
Native wiring accepts only separately configured VibePublish secret references,
not EventsBot sessions. Real operations still require appropriate authorization.

HTTP /v1 and MCP /mcp/ use bearer service tokens; mutating HTTP commands require
Idempotency-Key. Private assets use /v1/assets/{id} and
vibepublish://assets/{asset_id}; catalogs use /v1/emoji/catalogs/{id}. Skill also
has resource/prompt/get_started access. Existing public OAuth/TLS/onboarding,
URL/ticket ingress, recovery UI, retention/history pagination, owner-wide
discovery and live analytics gates remain open. Video/stories, full mention/rich
coverage and unproved native-provider capabilities are not silently dropped.

MAX remains in its existing PR #2. Its current HEAD must be read before later
integration; no MAX code, new task or combined MAX+emoji run was performed here.
The shared port remains the archived additive entities_json interface. Complete
source delivery and full hosted regression, actual DevCoveer host controls,
permitted live-provider tests and owner acceptance remain separate release gates.
For access diagnostics, follow the existing [delivery proof rule](repository-workflow.md#proof-of-github-delivery).
