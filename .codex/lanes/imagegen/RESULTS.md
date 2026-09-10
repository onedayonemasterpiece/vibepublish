# Imagegen lane — new implementation

Status: implementation/offline verification **Not confirmed by user**;
installed-host activation and live canary **Not done**.

## Ownership / provenance

- Base: `dcfa9a7`; branch `agent/vibepublish-acceptance/imagegen`.
- New source: `adapters/codex_imagegen.py`.
- New regressions: `tests/visuals/test_codex_imagegen_new.py`.
- Canonical operations update: `docs/operations/devcoveer-imagegen.md`.
- No existing test, core, schema, MAX, production, secret or host config changes.
- No archive or previously blocked payload fetched, copied or restored.
- No live model call, generated image, deployment or push performed here.
- Root integrator owns changelog, integration, full-suite checks and remote delivery.

## Implemented / verified

Closed private operator config; exact CLI version/help probes; untrusted request
as stdin JSON; explicit Luna route passed through operator allowlist; exact
verified source staging; minimal environment; process-group timeout/cancel;
fsynced reservation + file lock + durable observation before spawn; restart and
concurrent submit do not retry an uncertain job. JSONL and final structured report
must agree. Exact returned thread/work directory, no traversal/symlink/hardlink,
image-byte decoding/hash/size and candidate-count gates precede import.

Actual process executor is separate from requested route; actual image model is
null. Success evidence is explicitly a structured agent report, not fabricated
native image-tool attestation. Raw event/reasoning/stderr text is not retained.
Unknown failures keep only exception class/local exit code, never private error text.

## Test evidence

- Initial delivered suite: `31 passed in 15.34s`.
- Additional test run after intermediate-message fix: `9 passed in 0.28s`.
- Final combined suites: `41 passed in 19.50s` after the final code change.
- `git diff --check` passed. Full suite is deferred to root integration because
  the domain lane is separate; this lane ran both applicable process suites.
- Compileall of the new adapter/test passed.
- A first new test run found the intermediate non-JSON agent-message bug (39
  passed, 1 failed); collecting only the final completed message fixed it. The
  first local edit command used an unavailable bare `python`; reran explicitly
  using the existing acceptance `.venv/bin/python`. No dependency install needed.
- Existing real subprocess tests cover timeout, cancellation, real SIGKILL,
  stale running receipts, forbidden tool events and VisualService/importer/
  selection/parent continuation, in addition to artifact validation.

## Host evidence / blockers

Read-only CLI inventory: `codex-cli 0.153.0`, package at VS Code extension
`openai.chatgpt-26.5901.22334-linux-x64`. All used exec flags appear in help.
The local launcher falls back because its older preferred extension is absent.
Fresh official CLI/config/model sources are linked in the operations document.

The installed feature inventory includes image generation, shell/unified exec,
apps, plugins, hooks, browser and code-mode host. Official docs establish several
individual disable gates, but no verified global native-tool allowlist or hard
per-job image-call budget. The removed `apply_patch_freeform` toggle is not proof
of no patch capability. Nested code-mode exclusions are not global denial.
Therefore no image-only attestation has been authored, and the adapter cannot be
safely enabled from the current evidence. Effective tool inventory, no-other-tools
controls, permitted auth/home and billed-call enforcement need genuine operator
verification. `candidate_budget` bounds imported files, not upstream calls.

Existing tests do not establish a native image event schema on CLI 0.153.0. New
native/unknown item types fail closed; adding support needs sanitized installed
contract evidence and a regression, not bypassing that gate. Model availability
and actual backend remain unproven for the proposed isolated host.
