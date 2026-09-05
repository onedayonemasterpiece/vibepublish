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
