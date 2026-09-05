# Local Codex image executor on DevCoveer

> **Active task:** the owner now requires [Codex implementation, real Imagegen,
> deployment and full product acceptance](../handoffs/codex-full-product-rollout-20260905.md).
> The old ChatGPT-stage prohibition on generation/deployment is not the scope of
> this new task. Actual host controls, permissions and budgets still apply.
> This task update does not prove activation or resolve missing source.

> **Current delivery is partial:** `adapters/codex_imagegen.py` received a
> request-safety block and is absent from this branch. Its interface, integration
> points and tests are delivered. The implementation description and process-test
> evidence below refer to the complete archived module, not a runnable remote
> executor. See [runtime status](social-runtime.md). Host activation stays disabled
> until the required controls and working implementation are actually verified.

Status: bounded process implementation **Not confirmed by user**. Installed-host
binding, image-only enforcement and real generation canary: **Not done**.
This uses the existing `ImagegenExecutor` / `VisualService` / verified importer;
it is not a coding-agent delegation or a new publication/billing ledger.

## Implemented source behavior

`adapters/codex_imagegen.py` exposes `CodexImagegen`. One new image-work job
reserves a private directory and fsyncs a submission marker **before** spawning
one fresh `codex exec` process. Image sources are hashed, decoded and staged as
private, exact-byte files. Arguments are a fixed documented CLI grammar; the
untrusted brief is JSON data on stdin, never shell text. An argv list is used,
not a shell. Only a fixed minimal environment is passed: no inherited API keys,
Telegram/VK credentials, Python/Node injection settings or proxy secrets.

The existing requested route `gpt-5.6-luna` is passed as the orchestration model
only when included in the operator's observed allowed routes. The profile and
exact version are operator-only configuration. Before each *new* submission the
adapter checks `--version` and the necessary `exec --help` flags. Those probes
cannot prove the image tool is installed, callable or isolated.

Transport uses the documented `exec --json`, `--output-schema`,
`--output-last-message`, `--cd`, `--skip-git-repo-check`, `--sandbox read-only`,
`--model`, `--profile`, `--image` and stdin prompt (`-`). It does **not** invent an
imagegen CLI command, REST API, background job ID, durable upstream inspect or
cancel API. No OpenCode package, Google route or API-key fallback is substituted.

Only one well-formed JSONL thread/turn, a terminal successful turn, a zero process
exit and a matching final structured result can produce a successful transport
receipt. The structured result contains exactly job_key, input_digest and exact
saved_paths. The last completed agent message must agree with that result file.
An absolute output path must be a direct file in this new job's
`work/generated_images/` or the *exact returned thread's*
`CODEX_HOME/generated_images/{thread_id}/`. Nothing scans for a newest image.
Duplicate files, foreign threads, traversal, symlinks, hardlinks, invalid/oversize
images and excess/missing candidates are rejected. Original bytes are copied to
flat per-job artifacts and verified again by the existing importer.

The official inspected exec JSONL enum does not include a native image-generation
item. Accordingly, the evidence is explicitly
`structured_agent_report_not_native_image_tool_attestation`. This adapter does
not invent such an event or treat the agent's model-name claim as telemetry.
`requested_route`, actual process executor (`local-codex-exec`) and actual image
model are separate; **actual_model remains null**. Private control receipts keep
the final path report, stream hash, thread ID and numeric token usage. They do
not store or expose reasoning text, raw prompts, auth data or arbitrary event logs.
The image-tool model/backend must be added only from verified installed-host
native evidence, never inferred from the orchestration model or source constants.

Timeout/cancel kills only the owned local process group. A stopped submitter or
nonzero exit is not proof of upstream cancellation/no billing. Reopening a job
without its completed receipt returns `unknown`, even if images are visible.
A surviving submitter holds a file lock; after process death a stale `running`
receipt is read as unknown. New workers never signal stored PIDs or resubmit.
The core's original dispatch marker, job budget, selected hash, immutable lineage
and single parent continuation remain authoritative. Transport files are private
provider-style receipts, not a second business scheduler.

## Activation is deliberately not claimed

Historical read-only DevCoveer connector calls during source implementation resolved
`/home/dev/projects/vibepublish` and the live Codex model catalog, including Luna.
The exposed connector has no direct terminal/version/skill-read method. Its
start_task/continue_task methods were **not** used to delegate development or to
run a diagnostic agent. An installed model catalog is not the host CLI/tool schema.
The specific missing evidence concerns **Codex on DevCoveer**, not the owner's PC.

The owner-only worker flags are `--codex-imagegen-config PRIVATE_JSON` together
with `--imagegen-artifacts PRIVATE_DIRECTORY`. No option is enabled by default;
fake and Codex image executors are mutually exclusive. JSON must be an owned
0600 regular single-link file containing exactly:

- command: one absolute Codex executable path;
- codex_home: the dedicated restricted Codex home (no credential copying here);
- expected_version: exact output observed on that DevCoveer executable;
- profile: the actual installed dedicated image-only profile;
- allowed_routes: exact observed orchestration model IDs;
- attestation_ref: SHA-256 of the operator's reviewed host-contract evidence;
- image_only_isolation_verified: the boolean true **only after** that review.

The attestation is trusted operator configuration, not a self-verifying security
proof or authorization supplied through MCP. Setting a boolean cannot create a
sandbox. A production operator must first establish dedicated OS/profile isolation,
no coding/shell/file-edit/MCP tools, only the authorized image tool and sources,
no autonomous retries, and an enforced per-job image-call budget. `read-only`
filesystem mode alone does **not** prohibit network/MCP tools. Detection of a
forbidden JSONL item is only a fail-closed observation; it may occur after an
attempted effect and is not claimed to prevent it. Likewise candidate_budget
bounds accepted artifacts here; it is not proof of upstream billed call count.
Until those installed-host controls are verified, leave the executor disabled.
No fabricated example version, auth file, model backend or permissive sandbox is
shipped as a working configuration.

A host metadata/profile check needs no generation. The historical archive stage
forbade generation and deployment; the [new owner-authorized rollout](../handoffs/codex-full-product-rollout-20260905.md)
requires actual generation and deployment after the relevant controls are verified.
This does not grant new social-destination rights or bypass a tool's refusal.
The generation runtime remains image-only; Codex engineering authority for this
new task is distinct from the runtime generator's restricted tool permissions.

## Reproducible offline verification

`python -m pytest tests/visuals/test_codex_imagegen.py -q`

The executable double is `tests/visuals/scripted_codex_cli.py`, explicitly not a
real Codex/model. Tests launch real processes, enforce exact source bytes/argv,
exercise event/file mismatches, identity/privacy/size/path gates, cancellation,
timeout, real SIGKILL and restart without a second submit. A full existing
VisualService/worker/importer/selection/parent-continuation test uses those actual
subprocess artifacts. This is stronger than mocking submit(), but not evidence
of the installed DevCoveer CLI or image tool behavior.

Primary contracts inspected (not installed-host verification):
- https://developers.openai.com/codex/cli/reference/
- https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs
  (observed blob `30df7f176a02c5283405a70fac2d5ef9acdcb66e`)
- https://github.com/openai/codex/blob/218e8df92683fee5d052fdde3d8e502f951227d7/codex-rs/ext/image-generation/src/tool.rs
  (native saved_path support; not proof this revision is installed on DevCoveer)
