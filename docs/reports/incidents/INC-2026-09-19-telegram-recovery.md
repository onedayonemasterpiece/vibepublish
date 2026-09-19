# INC-2026-09-19-telegram-recovery

Status: `Not confirmed by user` — Telegram provider read verified on DevCoveer2.

## Summary

The restored public OAuth MCP answered requests but Telegram thread reads returned
`telegram_connection_unavailable`. Public MCP availability did not establish
provider readiness. The existing designated session is now wired and a public
MCP thread read has succeeded.

## Impact

Telegram reads and publications were unavailable on DevCoveer2. Reads now pass;
publication effects were deliberately not exercised by this recovery check.

## Root Cause

The restored ledger had no provider connections and the worker ran without
native adapters. Credential mapping was not completed. The owner confirms that
`.env` contains an existing specifically designated session; the earlier claim
that a new session was necessary was unsupported.

## Fix

Mapped `/home/dev/.env:TELEGRAM_VIBE_PUBLISH` to the canonical in-memory
`VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE` reference with the explicitly selected
`TELEGRAM_API_ID` / `TELEGRAM_API_HASH`. Registered `devcoveer2-telegram` in the
existing tenant. Switched `vibepublish-worker.service` to the production worker's
explicit Telegram-only mode with exclusive session ownership. No credentials
were replaced and no new Telegram authorization was performed.

## Regression Checks

Require provider-backed read completion; tools/list and health alone are
insufficient. Never retry historical publication effects during recovery.

## Release Evidence

- Public HTTPS OAuth + MCP initialize/tools/list: PASS.
- `vibepublish_read` thread `https://t.me/c/4379835477/5`: PASS;
  operation `op_a143aaa47000472990ff350e9d240303`, state `verified`, three items
  with source `provider`. Content and credentials were not printed or archived.
- Deployment, Telegram direct-target and OAuth regressions: 70 passed.
- Worker: active/running with zero restarts after activation.
- Verification-only OAuth grant revoked; existing ChatGPT grants untouched.
- VK, MAX and publication acceptance are not implied by this read result.

## Follow-Ups

VK and MAX remain separate unresolved provider recoveries.
