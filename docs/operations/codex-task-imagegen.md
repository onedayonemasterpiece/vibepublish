# Ordinary Codex task image executor

Status: owner-authorized ordinary-task route; implementation **Not confirmed by
user**. Real worker/publication acceptance remains an integration check.

The owner's September 5 correction authorizes ordinary Codex tasks using built-in
`image_gen` on the existing user's Codex quota. It supersedes the earlier demand
for an image-only native-tool allowlist and a hard upstream image-call gate.
There is no API fallback, separate provider SDK, or claim that a coding task is
an image-only sandbox. The existing legacy adapter is not modified by this lane.

## Wiring

```python
from pathlib import Path
from adapters.codex_task_imagegen import CodexTaskImagegen

executor = CodexTaskImagegen(
    Path('/approved/private/stand-state/imagegen'),
    codex_home=Path('/home/dev/.codex'),
    timeout_seconds=600,
)
```

The class implements `ImagegenExecutor`: `submit`, `inspect`, `find`, `cancel`,
and `artifact_root`. Call `await executor.close()` when this executor instance
is shut down. The artifact root and its sibling `<name>-tasks` must be private,
owned by the service user, and writable. Each job has its own working directory
and staged sources. The service must permit the **existing approved** Codex home
to write its thread state and `generated_images`; read-only home protection alone
is insufficient. Changing worker service paths is deployment-owned work, not an
instruction to modify shared Codex services or copy authentication credentials.

The client launches its own `/home/dev/.local/bin/codex app-server --stdio`,
checks `codex-cli 0.153.0`, and initializes the native protocol. It does not import,
modify, attach to, or stop the shared DevCoveer bridge. It passes only an explicit
HOME/CODEX_HOME/PATH/LANG environment. API keys and social-service environment
variables are not inherited. Codex reads its existing authentication itself;
this adapter never reads or serializes the credential file. Thread configuration
requests ChatGPT login, built-in image generation and workspace-write, with the
orchestration model pinned to `gpt-5.6-luna`.

This is normal task execution, not OS isolation from all files or credentials
accessible to that Unix user. Source images are supplied as native `localImage`
inputs; brief text, including quotations, is preserved in JSON. The task asks
for one image call per candidate, no retries, no placeholder, no API fallback,
and no publication. Up to four accepted candidates and a finite deadline are
validated locally. This is **not** a hard billable-call cap or price quote.

## Durability and recovery

A private, fsynced job receipt is created before `thread/start`; the thread ID
and a `turn_start_pending` marker are persisted before `turn/start`. The turn ID
is then persisted. An uncertain remote response leaves `unknown`; repeated
`submit` with the same job/digest does not start or continue another turn.

`inspect` and `find` use only `thread/read` for that saved thread. If the initial
turn response was lost, the sole turn in that dedicated thread can be recovered;
multiple or missing turns remain unknown. No `thread/resume`, `turn/start`, or
history search is used by recovery. A lost thread-creation response with no saved
thread ID remains unknown and is not recreated automatically.

Deadlines schedule an interrupt while this executor lives; post-restart polls
also enforce the saved deadline. `cancel` interrupts only the saved thread/turn
using `turn/interrupt`, never a shared process or unrelated thread. If observation
or interruption is unavailable the outcome remains unknown, not fabricated as
cancelled. Process shutdown may interrupt owned running tasks; saved identities
remain available for readback, not automatic resubmission.

## Native artifact evidence

Only `imageGeneration` items from the exact saved turn can produce accepted
artifacts. Final assistant text, shell output and claimed paths are insufficient.
The number of native items must equal the authorized candidate count. Each item
must be completed without a failure and name a PNG inside:

`CODEX_HOME/generated_images/<saved-thread-id>/`

The importer rejects traversal, symlink ancestors/files, hardlinks, foreign
ownership, non-regular and oversized files. Native saved bytes must equal the
native event's decoded base64 `result`. MIME, dimensions and SHA-256 are verified
before copying to a private immutable hash-named job artifact. No image is drawn
or substituted locally. The existing service importer independently verifies
that artifact again.

Observation `usage_json` contains only nonnegative numeric counters:
`candidate_limit`, `native_images_completed`, and `imported_artifacts`, matching
the shared VisualService contract. These count accepted output, not billed calls.
Thread/turn IDs, observed orchestration model, native item IDs/paths/hashes and
the candidate-limit policy remain in the private task receipt. The execution
reference (job key) binds the shared provenance to that private receipt. The
image model ID is unavailable in this event contract, so `actual_model` remains
null; it is never fabricated from the requested Luna orchestration model.
No reasoning or full private thread transcript is written into receipts.

## Verification evidence

The installed 0.153.0 schemas establish native `localImage` inputs and
`imageGeneration` items. The implementation uses the ordinary initialize,
thread/start, turn/start, thread/read and turn/interrupt protocol seen in the
installed bridge, without importing that service.

Read-only inspection of the previously completed owner canary thread
`01a07234-66ed-77d3-b42d-9645fd167d18` confirmed a completed native image item,
a thread-scoped saved PNG and a base64 result. This lane does not claim it
created that canary and did not request another image generation.

Offline tests in `tests/visuals/test_codex_task_imagegen.py` use explicitly
synthetic native-protocol fixtures. They cover marker ordering, uncertain
responses/restart, no resend, native evidence, candidate count, path/hash safety,
source inputs, quotations, environment minimization and scoped cancellation.
Fixture pixels are not evidence of real generation or publication readiness.

Official references: [App-server protocol](https://learn.chatgpt.com/docs/app-server)
and [built-in image generation](https://learn.chatgpt.com/docs/image-generation).

Lane validation on 2026-09-05: full repository pytest passed (434 tests and
199 subtests; two existing dependency-deprecation warnings); visual suite passed
(126 tests). The 17 focused adapter tests were rerun after the final directory
fsync hardening and passed. Compileall and diff checks passed. The new client
also read the existing canary without starting a turn and verified its native
PNG against the native base64 result: SHA-256
`b03be1b7b0242035f7c19d5e0594e1501182ed35801d4be7dffc3a15a3626610`,
1,989,613 bytes. No new generation or publication was performed by this lane.

### Numeric usage contract regression — 2026-09-05

The initial adapter incorrectly put rich task metadata in `usage_json`, while
`VisualService.process` accepts only nonnegative numeric usage values. An actual
Application/Worker/VisualService integration test reproduced terminal rejection
as `blocked / imagegen_usage_invalid`. The corrected adapter keeps identities
and native receipts private and exposes numeric counters only. The regression
starts with a native-shaped running task, observes completion, commits a verified
candidate and asserts that `turn/start` was called exactly once.

This is not evidence explaining a separately reported early
`imagegen_processing_unresolved` result. That generic failure was not reproduced
by this integration test; the service catch discards the original exception
class. Do not equate it with the confirmed usage validation failure.

After a core operation is terminal `outcome_unknown`, adapter readback can still
recover the same native thread, but cannot reopen that core operation. Current
worker crash recovery applies to unfinished leased work, not `complete=1` /
`work_state=done` operations. No automatic resend or database status edit is
performed by this adapter. A future authorized core reconcile action would need
fencing, authority rechecks, the same saved execution identity, dispatched-only
readback and candidate CAS; this fix does not introduce that action.

Fix validation: 18 focused adapter/service tests passed; all 127 visual tests
passed (two existing dependency deprecations); compileall and diff checks passed.
No live calls, image generations, production database edits or deployments were
performed during this regression fix.
