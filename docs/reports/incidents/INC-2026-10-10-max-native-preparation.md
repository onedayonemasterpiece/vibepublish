# INC-2026-10-10-max-native-preparation

Status: `Open` / live final mutation acceptance pending.
Registered incident: `inc_b61df688a29d6109383cbaec`.

## Summary and Impact

Owner MAX scheduled publish and native reschedule on deployed source
`a567997e2c7d39dfd56d1d5f6d8606331d14fc8a` failed before dispatch.
Historical generic catches discarded the underlying exception. Those original
exceptions cannot be reconstructed, so subsequent reproductions are not falsely
attributed to the old attempts. The native museum queue item remained unchanged.

## Root Cause and Fix

Reproduction found two concrete preparation failures:
- right click returned without a visible native context menu; the next menuitem
  action waited until timeout. Exact current Russian menu labels were verified.
  Reopen at most once, only for an absent menu and the same connected DOM handle,
  route, bound authored semantics, native scheduled clock and ordered media.
  Live evidence showed unchanged caption HTML, connected handle and media but
  changing aggregate row.textContent after the first right click. Exclude only
  surrounding UI metadata; changed authored links/text, time and media still
  reject. No menu-action or confirmation retry.
- Chrome 153 exited with SIGSEGV while downloading an existing queue photo.
  Production Playwright was 1.57. Cleanup then hid the first failure. Preserve
  original failures and log only exception class/phase. A compatible isolated
  Playwright1.63 run completed the exact original photo hash and calendar checks.
  Later runs reproduced the same native SIGSEGV with Playwright1.63 and both
  host Chrome153.0.8010.47 and bundled Chrome for Testing153.0.8010.12.
  Driver version alignment is therefore not a proven crash fix. Pinned headless
  shell153.0.8010.12 completed full-photo reschedule preparation once; further
  comparison and host RAM/cgroup/OOM correlation are required.

Playwright1.63 release notes explicitly test Chrome153:
https://playwright.dev/python/docs/release-notes

## Regression Checks and Evidence

Offline tests exercise first-click/second-click/no-menu cases, detached/text/
media/route drift, unexpected menu, full publish/reschedule calendar preparation,
named link and uploaded photo retention, and refusal after arm without a click.

Live owner-authorized diagnostics used the Vibe runtime profile, a tomorrow time,
and both a checkpoint stop before arm and a UI submission tripwire:
- publish preparation reached MAX_PREPARED at 07:58:50 UTC;
- full-media reschedule reached MAX_RESCHEDULE_PREPARED at 08:02:37 UTC using
  Playwright1.63 and Chrome153; normal browser exit, worker restored active.
No live native Save/Send was performed by these diagnostics. The owner confirmed
that the tool cancellation was not their action. A later read-only draft check
verified an empty composer and zero attachment previews. Final native write/
readback is pending. Further local browser probes are paused while investigating
RAM/cgroup limits and concurrent unrelated server work; no unrelated process is
stopped or inspected for private content.

## Release Evidence

Initial candidate501fd4b: CI passed1323 tests and248 subtests per Python3.12/
3.13, failing only an existing read-recovery error-code assertion. Preserve that
error contract at the copy-reference boundary and rerun the complete gate on the
updated source. Exact final release and production pair verification pending.
Earlier public HTTPS schema fix must remain in ancestry. Canonical dirty checkout
must not be overwritten.

## Follow-Ups

Complete native post scheduling/rescheduling through the existing MCP contract
with ample future-time margin; verify provider IDs, times, named links and photos.
An expired frozen publish plan cannot be changed by retry_failed: verify zero
dispatch and no pending recovery, then use the explicitly changed future intent.
