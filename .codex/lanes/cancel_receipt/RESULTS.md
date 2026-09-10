# Cancel receipt optional timestamp regression

Status: implementation/offline verification **Not confirmed by user**.
Root owns integration, changelog and re-reading the existing live cancelled
operation. No live provider action should be retried for this formatting bug.

## Root cause / narrow fix

Native cancellation preserves the old scheduled timestamp on the observed item.
Worker.finish_child correctly preserves it as effective_at, but previously also
emitted requested_at:null from the cancellation plan. The optional MCP timestamp
property is string-only when present. Store.receipt projected that null verbatim,
so a correctly cancelled operation could not pass status output validation.

- Worker emits requested_at only when the plan has a non-null value.
- Store projects legacy requested_at:null as an omitted optional property.
- All persisted attempts, plans, checkpoints, operations and event history remain
  untouched during receipt projection. No schema change or migration.
- Valid requested/effective/observed times, state and native identity preserved.
- Runtime diff: seven added lines, one removed across worker.py and storage.py.

## Verification

- Both new-format and legacy-null regression cases failed before the fix.
- New tests: `2 passed in 7.18s` after fix.
- Each test uses the actual native Telegram adapter against an offline scripted
  transport, then real local MCP SDK/server status and its published JSON schema.
- Cancel observation retains former scheduled_at while plan scheduled_at is None.
- New persisted result omits requested_at; legacy test confirms business rows are
  unchanged by Store, Application and MCP receipt reads.
- No second provider action; normal schedules still retain both timestamps.
- Compileall of changed/new Python files and git diff --check passed.
- Full runtime + native core integration: `50 passed, 6 subtests passed in 26.14s`.

## Scope / integration

Separate commit after previously integrated 503d9f2. Cherry-pick only this new
commit. Owned files: social_operations/worker.py, social_operations/storage.py,
tests/runtime/test_cancel_receipt_schema.py, the dedicated operations note and
this result record. Existing tests/contracts unchanged; root native worker script
untouched. No live RPC, secrets, database/history repair, deployment or push.
