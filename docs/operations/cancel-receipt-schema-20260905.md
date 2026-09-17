# Cancel receipt optional-timestamp correction — 2026-09-05

Status: implementation/offline verification **Not confirmed by user**;
post-integration live status recheck remains the integrator's responsibility.

## Summary / impact

A native cancellation can be confirmed and durably recorded as cancelled, yet
status output fails the MCP response schema because its delivery contains
`requested_at: null`. This is a receipt-format defect, not evidence that the
provider cancellation failed. Do not resubmit or repeat the provider action.

## Root cause

The native adapter retains the cancelled item's former scheduled time as
historical evidence. `Worker.finish_child` copies that timestamp as `effective_at`
and unconditionally adds `requested_at` from the cancellation plan, which has no
new requested delivery time. `Store.receipt` then projects this null verbatim.
The canonical optional `requested_at` property accepts a date-time string when
present, not JSON null (`contracts/social_mcp_v1.py`).

## Bounded fix / compatibility

Omit `requested_at` when the new result has no requested delivery time. At receipt
projection only, omit legacy persisted `requested_at: null`; preserve the stored
attempt/result, plan, checkpoint, operation and event history unchanged. Retain
valid requested/effective/observed timestamps, native cancellation state and item
identity. No schema relaxation, migration, ledger rewrite or provider retry.

## Regression checks / release evidence

The new `tests/runtime/test_cancel_receipt_schema.py` reproduces the real native
adapter shape: cancelled observation retains the old scheduled time while its
plan has no new time. Both new-format and legacy-null cases failed before the
fix and pass afterward. Each calls a real local MCP server with the official SDK,
validates the published status output schema, and confirms no second provider
action. Business operation/attempt/event rows remain byte-for-byte unchanged by
legacy read projection. A normal schedule still retains requested/effective times.

Live cancellation/readback evidence is owned by the integration run, not this
isolated code lane. No live Telegram calls or credentials are used here. After
integration, re-read the existing cancelled operation; do not repeat cancellation
or edit database/history to repair the response.
