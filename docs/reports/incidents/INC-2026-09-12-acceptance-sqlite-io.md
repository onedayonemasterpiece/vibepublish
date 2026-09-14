# INC-2026-09-12-acceptance-sqlite-io

Status: `Open`; affected startup reliability requirement: `Not done`.

## Summary

Existing acceptance worker journal reports SQLite `disk I/O error` during claim.
No destructive recovery or weakened SQLite durability is authorized or applied.

## Impact

Worker reliability is unverified; no successful deployment or live Telegram
acceptance is claimed. External server MCP remains reachable in the bounded check.

## Timeline

- 2026-09-12 08:31:27 UTC: OperationalError, exit status 1/FAILURE.
- 2026-09-12 08:31:32 UTC: journal records worker restart/start.
- Stage A/B inspection: ledger and OAuth DB immutable quick_check each `ok`.
- Stage D attempt: user bus unavailable; worker stop not established.

## Root Cause

Not established. Sanitized traceback locates failure at
`Store.connection`, `PRAGMA synchronous=FULL`, reached from `Store.claim` and
`Worker.run_once`, not a Telegram credential/session database. Root disk has
4.5GB available (95% used). Neither that utilization nor quick_check proves a
root cause. Ledger header is WAL, with no visible current WAL/SHM sidecars in the
inspection view; immutable connection journal_mode reports delete and is not
proof that the live ledger uses rollback mode.

## Fix

Blocked pending approved control of the existing services and writable runtime
state. No DB files removed, no durability setting changed, no broad cleanup.

## Regression Checks

Offline runtime SQLite tests and new Telegram durable-response restart tests pass.
These do not establish live worker health or resolve this incident.

## Release Evidence

Existing port 18766 listener and authenticated external MCP checks succeed.
Service ActiveState/SubState/MainPID/NRestarts unavailable from this task's bus.

## Follow-Ups

Stop existing worker then server through approved host control; establish a safe
consistent DB backup and inspect runtime ownership/storage/WAL permissions. Only
then perform a conservative SQLite/WAL writable check, preserve all data, and
start server/check 18766/start worker in order. Recheck both journals and restart
counts. Never manufacture the absent target binding to unblock live acceptance.
