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
