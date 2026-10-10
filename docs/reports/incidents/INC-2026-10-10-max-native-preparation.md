# INC-2026-10-10-max-native-preparation

Status: Live social effects verified; phase-budget correction pending final CI/deployment.
Registered incident: `inc_b61df688a29d6109383cbaec`.

## Impact and evidence limits

Owner MAX scheduled publish and native reschedule on source
`a567997e2c7d39dfd56d1d5f6d8606331d14fc8a` failed before dispatch.
Generic catches discarded the original exceptions. Later reproductions do not
prove the historical attempts had the identical underlying cause.

## Preparation repairs

A native right click sometimes returned without a visible menu. The adapter now
observes the actual menu and retries absence once, before arm, on the same
connected control and unchanged authored text/entities, native clock and ordered
media. Unrelated visible menus or subject drift fail closed. Only proven volatile
row metadata is excluded. Menu actions and final confirmation are never retried.

Full Chrome153 crashed with SIGSEGV during native photo download under both
Playwright1.57 and1.63, including bundled full Chrome. Version alignment alone
was disproven as a fix. Production now uses an isolated pinned Playwright1.63
runtime and official Chromium headless-shell153.0.8010.12, with two successful
full-photo preparations and subsequent actual MCP reads/reschedule/publication.
The native C++ crash cause remains unproven. Original exceptions survive cleanup;
compose diagnostics record step, exception module/class, elapsed time and
repository traceback locations, without post text, URLs or DOM.

Host audits found zero OOM kills since boot and no stale diagnostic browsers.
The exact successful preparation downloaded the original124384-byte1080x1080
JPEG to a writable UID1001 temporary directory, with3.70GB and over1million
inodes free. Available RAM stayed above3.10GB; job peak991MB; job memory limits
were unlimited and OOM/limit counters remained zero. These observations exclude
an OOM kill for the recorded crashes, not every possible allocator failure.

## Proven completion-budget defect and correction

The real lecture command completed preflight at09:16:22.311 UTC, committed its
single durable dispatch marker at09:17:23.188, then returned unknown at
09:17:52.619,90.31 seconds after preflight. It had already saved the new native
identity and original downloaded-photo evidence. Preparation consumed53 seconds;
the existing90-second execution scope left insufficient time for the full
post-dispatch independent readback. Explicit observation-only reconciliation
completed in49.7 seconds without another effect.

The worker and scheduled MAX adapter now start a fresh bounded observation budget
only after the original before_effect guard successfully commits dispatch.
Preparation retains its original deadline. Scheduled publish/reschedule execute
for at most90 seconds before dispatch plus90 after it (adapter limits may be
shorter), with the existing bounded finalization. No additional Send/Save,
observation weakening, automatic effect retry, or permission bypass is added.
An exhausted post-dispatch budget still becomes outcome_unknown. Cancellation
and restart retain the existing observation-only recovery contract.

## Acceptance and regression evidence

- Exact d63b2da full CI passed:
  https://github.com/onedayonemasterpiece/vibepublish/actions/runs/38038744898
- Normal MCP reschedule verified museum at20:00 Kaliningrad with original photo.
- Normal MCP lecture publication created one native post at13:30 Kaliningrad.
  Independent native read verified all three named links and photo. Its
  observation-only reconcile finished scheduled with download_binding and
  finalized quarantine at09:20:47. Both authoritative posts must not be retried.
- Lecture source SHA2569dc4ae5f7e70d12ef9124e4deb5e43b5b2e7ec04ea5a60ae1d8b570e5ddda61e
  is causally bound to MAX's transcoded native photo
  SHA2569f01328df037b1938fe10a2956fefdf8e0bb0b8345f433f4bb2436692c11a821,
 182205 bytes, through original operation/attempt/plan/native identity.
- Offline tests cover menu absence/drift, photo/link/calendar retention, precise
  content-free diagnostics, pre-dispatch expiry, separate post-dispatch budget,
  missing receipt, cancellation/restart, and at most one external effect.

Earlier uninstrumented compose timeouts did not reproduce in controlled
preparation, exact preflight, or prior-read sequence; do not claim their exact UI
cause is established. The narrow logging patch preserves evidence next time.

## Release boundary

Preserve the earlier public HTTPS schema fix, existing account/profile/allowlist,
and rollback source/interpreter. Do not modify the older dirty canonical checkout.
No further live test posts are required: final budget verification is deterministic
offline regression plus read-only service/native acceptance of the existing posts.
