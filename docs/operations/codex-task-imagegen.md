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

### Private observation diagnostics

On an inspect/find remote-read or artifact-processing exception, the private task
receipt now records `last_observation_error` with the exception class and up to
16 traceback frames (`file` basename, numeric `line`, `function`). It never stores
exception messages, argument values, locals, source lines, prompts or reasoning.
The same diagnostic is saved before re-raising an observation-conversion error,
including conversion of an already-terminal receipt. Cancellation is recorded
then propagated; it is not converted into success or an automatic resend.
Diagnostics do not enter public usage/provenance. A failure to acquire/read/write
the private receipt itself cannot reliably be recorded in that same receipt.

A read-only lookup of the reported original task
`01a07247-6ab5-71c2-aa26-3f516667d33f` returned its completed turn
`01a07247-74ba-7543-86a5-5af8bfdff04f` and one native image item. This confirms
present readback only, not its earlier in-flight response. Official app-server
documentation allows `thread/read` with runtime `active` status; the installed
DevCoveer bridge also uses that read to locate in-flight turns for cancellation.
No general in-flight rejection rule was found. Missing/ambiguous saved turns or
transient read errors can still produce unknown; none is asserted as the proven
cause of the original four-second generic service failure.

Diagnostics validation: 22 focused tests passed, including the actual service
running-to-candidate regression, sanitized error frames, malformed read response,
observation conversion failure and cancellation propagation. Compileall/diff
checks passed. No new task, generation, production DB change or social write was
performed for this diagnostic change.

### Initialization cleanup regression

The app-server client now tracks successful initialization explicitly. Process
assignment alone does not mark it ready: the initialize response, expected Codex
home and initialized notification must all succeed. Any handshake error, timeout
or cancellation clears the flag and closes only this client's owned process and
reader before propagating the failure. A later independent request may start a
fresh handshake; the failed caller request is never replayed automatically.

An offline regression reproduced the old process leak on initialization rejection.
Additional fixtures cover home mismatch, notification write failure and cancelled
initialization. The full focused adapter/service file passes 24 tests and three
subtests; compileall and diff checks pass. No live calls or generation were used.
This confirmed lifecycle defect is not asserted as the cause of the separately
reported four-second core failure after a successfully submitted native turn.

### Execute-only namespace traversal — confirmed early failure cause

The operator reproduced the early generic service error under the exact worker
systemd protections: `_read` failed opening `/` with `O_RDONLY | O_DIRECTORY`
because the namespace exposes an execute-only root. This happens while loading
the receipt, before the observation try/diagnostic block; it is independent of
the native task's separate bwrap/AppArmor failure.

Secure reads now pin root and ancestor directories using Linux
`O_PATH | O_DIRECTORY | O_NOFOLLOW`. The final file remains opened read-only with
`O_NOFOLLOW`; ownership, regular-file, hardlink, size and hash checks are unchanged.
The reader needs path traversal, not directory listing permission. No sandbox,
systemd protection or host AppArmor setting is relaxed.

Two regressions failed against the old implementation and pass with the fix:
an actual execute-only ancestor, and inspection of root/ancestor/final-file open
flags. All 26 focused tests and three subtests pass; compileall/diff checks pass.
The exact systemd production read-only recheck belongs to the operator; this lane
made no live calls or production writes for the fix.

### Trusted skill preloading without shell commands

Before a new native thread is dispatched, the executor reads only the fixed
installed `CODEX_HOME/skills/.system/imagegen/SKILL.md` through the secure reader,
with a 64 KiB bound and UTF-8 validation. The whole skill is injected using the
installed 0.153.0 `thread/start.developerInstructions` field. The private job
receipt stores `skill_snapshot` (fixed path, byte count and SHA-256), not another
copy of the skill. Missing, oversized or symlinked skill files fail before any
native request; existing dispatched jobs remain read-only recoverable and are
not resubmitted if the installed skill later changes or disappears.

The trusted context truthfully states that the full skill has already been
loaded and attached `localImage` inputs are already visible in the conversation.
The task should call built-in image_gen directly: no shell cat, supporting-file
read, CLI/API fallback or filesystem copy is needed. The executor, not the model,
imports native saved image bytes. Sandbox settings remain workspace-write;
no legacy sandbox flag, AppArmor setting or systemd protection is changed.
This avoids an unnecessary shell dependency but does not claim that model
compliance or a future native generation has already been verified.

Validation: 31 focused tests and three subtests passed, including fixed-path/full
skill context, private hash, missing/oversized/symlink guards, unchanged sandbox,
source input preservation and no replay when a skill disappears after dispatch.
A local read-only preload smoke loaded the installed skill without a native
request; no thread or image generation was started. Compileall/diff checks pass.
