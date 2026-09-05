# VibePublish runtime checkpoint

Status: **Not confirmed by user**. Implementation in progress on
`work/vibepublish-core-20260904`; no deployment or live provider capability claim.

The first committed integration boundary is `adapters/port.py`:
`ProviderAdapter.inspect/prepare/execute/read/reconcile`, frozen request/asset/item
snapshots and awaitable `Hooks.emit_progress/checkpoint/before_effect`.
The core owns authorization, durable dispatch, fencing and retry decisions.
MAX Web must implement this port, not another business database or MCP server.
An unwired adapter reports needs_auth/unknown, never simulated publishing success.

The independent core uses `social_operations/`; schemas remain canonical in
`contracts/social_mcp_v1.py`. The only CI is `.github/workflows/ci.yml` on a
GitHub-hosted Python 3.12 runner. No social credentials, live writes or self-hosted
runners are used. The maintenance MCP SDK is pinned to 1.29.0; protocol/client
compatibility is a runtime test gate, not inferred from schema tests.

Contract baseline rerun locally: 22 unittest methods, 16 schemas, 125 golden and
44 negative calls. These are not runtime or live-provider tests. Subsequent code
batches add the SQLite service, actual MCP/HTTP transport and executable fake
provider integration tests here.

## Follow-up: MAX and actual imagegen plugin — 2026-09-05

The full SQLite/native/visual implementation is in the separately delivered
`vibepublish-native-visual-20260905.zip`, LOCAL HEAD
`870e2a4304c57ef5dd7152de63df1db6431a942b`, not in the remote seed above.
The subsequent MAX handoff and passive plugin-inventory batch do not import it.
Shared port in that archive: `adapters/port.py`, LOCAL commit
`25de851b911d02fc9ece2a7e193743758bfa48c1`; the remote seed port is older.

Use [the updated separate MAX task](../handoffs/max-web-codex-20260905.md).
Read [verified imagegen sources and host-binding limits](../reference/imagegen-plugin-discovery-20260905.md).
Owner success in Codex/OpenCode is accepted; VibePublish still needs the actual
host tool binding. Do not substitute API-key CLI or Google image generation.

Inventory tests run without credentials or plugin execution. Full-source local
regression on the archived implementation plus inventory: 151 nonvisual tests
plus 199 subtests, and 38 visual tests, in separate successful commands. An
earlier monolithic invocation timed out without a completed summary. These are
not locked-install or remote full-runtime CI evidence. MAX/imagegen canaries and
deployment were not run. Do not overwrite these newer docs with the old archive.


## Latest owner corrections and actual work queue — 2026-09-05

Telegram custom/premium emoji is a required product capability, not merely an
inline alias in the schema. [The workflow and donor findings](../features/social-operations/telegram-custom-emoji-v1.md)
cover set links, private numbered previews, ordered sequences and reusable rules.
Runtime compilation/catalog/selection remains **Not done**. This batch read donor
code/tests/incidents and designed the delta; it did not execute those donor tests
or implement the emoji runtime. No new pass count is claimed for this design.

Imagegen must use local Codex ON DEVCOVEER, where the owner reports it works.
The researched third-party OpenCode plugin is not the target; do not request a
probe on the owner's personal computer. Actual host binding/process result
recovery is still **Not done**; scripted process tests can be written in ChatGPT
without delegating development or running a generation canary.

MAX PR #2 now exists at `d0bceb2efd1ab2da83e6553a61f1a33b31a7b755`.
Its CI 33947076136 verify job is successful; the imagegen-inventory step is skipped
because that file is absent on the main-based MAX branch. 37 MAX + 22 contract
tests are the reported MAX checkpoint, NOT core/MCP/live integration. Runbook
states FixtureDriver accepts only loopback synthetic pages; actual port wiring,
production factory and observed live selectors remain missing. ZIP was not
mounted in that Codex task. The original ZIP is present in this ChatGPT session;
103 source hashes, cumulative patch and port hash were checked again. This does
not move bytes to Codex automatically. Reattach the original archive to the same
MAX task; no duplicate task or MAX implementation in ChatGPT.

Use [the continuation handoff](../handoffs/core-emoji-imagegen-continuation-20260905.md).
Full core remote delivery/locked CI remains the first release blocker, followed
by the implemented slices and existing explicit provider/deployment gates. The
new design/docs do not make the archived runtime remotely delivered.
