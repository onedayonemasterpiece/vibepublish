# INC-2026-09-19-vk-recovery

Status: `Open` — VK recovery `Not done`.

## Summary

DevCoveer2 VibePublish has a verified Telegram read path, but no VK connection
registered in its restored ledger. Passing offline tests or MCP health checks
does not prove VK works.

## Impact

VK operations are unavailable through the restored public MCP.

## Root Cause

Provider recovery was left incomplete. The production worker supported either
Telegram alone or the full Telegram/VK/MAX topology, not an explicitly selected
Telegram/VK topology. Historical acceptance referenced `VK_ACCESS_TOKEN4`, which
was not found in the checked credential sources. The restored `.env` contains
multiple other VK tokens; their assignment to VibePublish is not yet confirmed.

## Fix

Prepare explicit provider selection without silently ignoring active connections.
Obtain the existing designated VK token variable name, register the connection,
and verify an actual read through public MCP. Do not create credentials, rotate
tokens, publish content, or borrow another product's credentials by guessing.

## Regression Checks

Keep the default full topology strict; preserve Telegram session locking and
legacy Telegram-only configuration. Require selected providers exactly once.
Require a completed VK provider read before reporting VK recovery success.

## Release Evidence

Explicit provider selection implemented; 37 deployment regression tests passed.
The running Telegram-only worker was not restarted and remains active with zero
restarts. VK activation and actual provider read remain pending the designated
existing token variable name; no VK provider PASS is claimed.
