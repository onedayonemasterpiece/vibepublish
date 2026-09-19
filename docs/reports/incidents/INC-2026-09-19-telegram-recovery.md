# INC-2026-09-19-telegram-recovery

Status: `Open` — Telegram recovery `Not done`.

## Summary

The restored public OAuth MCP answers requests but Telegram thread reads return
`telegram_connection_unavailable`. Public MCP availability did not establish
provider readiness.

## Impact

Telegram reads and publications cannot execute on DevCoveer2.

## Root Cause

The restored ledger has no provider connections and the worker runs without
native adapters. Credential mapping was not completed. The owner confirms that
`.env` contains an existing specifically designated session; the earlier claim
that a new session was necessary was unsupported.

## Fix

Pending: resolve the existing owner-designated session, register its connection in the
existing tenant, activate the native worker with exclusive session ownership,
and verify an owner-requested Telegram thread read through the public MCP.

## Regression Checks

Require provider-backed read completion; tools/list and health alone are
insufficient. Never retry historical publication effects during recovery.

## Release Evidence

Not yet accepted. Existing credentials must be preserved; new authorization is
not part of this recovery.

## Follow-Ups

VK and MAX remain separate unresolved provider recoveries.
