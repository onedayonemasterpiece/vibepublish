# Scoped media repair

Status: Not confirmed by user. Offline and live acceptance are reported separately.

Canonical behavior and verification requirements live in [the MCP contract](mcp-contract-v1.md#target-scoped-edits-and-managed-telegram-single-media-replacement).

A selected-destination edit retains the original publication identity, advances its common desired revision, and preserves untouched provider attempts and proof by reference. Every target exposes desired/applied revision and synchronization status. Uncertain or allocation-only siblings are never implicitly retried. A managed Telegram single-message media replacement requires a fresh exact read, same-principal verified lineage, asset integrity, an upload-time CAS recheck, and actual native media readback.

Code release alone does not authorize a provider mutation. The incident's corrected media replacement remains subject to the separately confirmed live action and verified readback.
