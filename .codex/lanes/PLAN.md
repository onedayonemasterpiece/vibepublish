# Acceptance continuation lane map
Base: dcfa9a7acf33c58bc5456aec517bf833892c3764
Integration: work/vibepublish-devcoveer-acceptance-20260905
R01 HTTPS domain: root, deployment/artifacts, serial shared-host writes.
R02 token to Saved Messages: root, private artifacts; no credential disclosure.
R03 resolve targets and live acceptance: root, private scripts/evidence; depends on access and R01.
R04 new Codex imagegen adapter: imagegen worker, high effort, separate branch/worktree.
R05 integrated real tests and closure: root; depends on R01-R04.
Worker ownership: adapters/codex_imagegen.py, tests/visuals/test_codex_imagegen_new.py if necessary, docs/operations/devcoveer-imagegen.md, .codex/lanes/imagegen/RESULTS.md.
Root owns all other files, changelog, integration report. No schema/core/old test edits without discussion.
No archives, no MAX/PR2/main/production modifications. Worker must commit, no push.
Integration order: worker commit review/cherry-pick, focused+full tests, isolated service activation only with verified controls, live evidence, closure.

## Owner continuation: prompt-first postponed visuals
Base: 7bec7bf. Requirements R06 original media without AI; R07 prompt-only generate/tune/compose with references; R08 explicit execute+future delivery may auto-select into provider queue, never elevate preview/standalone/immediate; R09 VK lovekenig postponed-only live lifecycle; R10 verified built-in executor and honest readiness.
Imagegen worker owns schema/visual normalization+selection/new tests/canonical visuals docs in separate worktree (high); root owns VK deployment wiring/tests, changelog, live evidence/integration. Edge agent read-only exact CLI controls investigation (no deployment). Merge visual lane before integrated suite and any generated scheduled live acceptance. Shared files/host operations stay serial. No MAX/main/old archive/credential disclosure.
R11 external original upload: asset_ingress worker owns server.py, new asset_ingress.py/tests/docs only, separate worktree; existing operation namespace, no migration/service/schema changes. Root merges after visual lane and tests combined. Pure-MCP host attachment bridging remains separate from HTTP binary ingress.

## Owner correction: ordinary Codex tasks, now/default and chat files
R12 ordinary Codex task with built-in image_gen uses owner Codex access/quota; no separate API. Prior inferred absolute image-only allowlist and hard billed-call prerequisite superseded, not falsely attested. Root owns deployment/wiring and docs correction; edge_renderer owns NEW codex_task_imagegen adapter/tests/doc only separate worktree (high). R13 execute visual can publish now when no delivery: imagegen worker visuals/schema description/tests, merge first. R14 native ChatGPT file input on existing visual tool: asset_ingress worker waits until R13 contract merged, then owns new importer+schema/service/tests. R15 Kaliningrad timezone/config and model-facing instructions: root. No MAX/main or shared bridge changes; VK live target remains postponed-only.

## Closure evidence (engineering statuses, not owner sign-off)
R01 Partial: public hostname works; shared-renderer persistence and TLS-renewal verification remain.
R02 Partial: Saved Messages35826 delivered/read back; user confirmation pending.
R03 Partial: Telegram native lifecycle/emoji/media verified; VK copied-photo binding blocked.
R04 Superseded for runtime activation by ordinary-task R12; legacy source preserved.
R05 Partial: integrated local suite and public service evidence recorded; no full hosted CI claim.
R06 Partial: no-AI original ingress/readback verified; actual current chat attachment handoff not observed.
R07 Partial: prompt-first generate/tune/compose native images verified; composition fully queued, failed task histories retained.
R08 Superseded by explicit NOW as well as scheduled execute R13.
R09 Blocked: VK photo owner/ID remapping lacks a verified automatic binding; no resend.
R10 Partial: native image receipt/path/hash verified; not a hard billed-call attestation.
R11/R14 Partial: HTTP and real MCP file-object ingress verified, client UI handoff unverified.
R12 Partial: ordinary Luna tasks live, no API fallback; owner acceptance pending.
R13 Partial: automatic scheduled composition verified; no-time live evidence tracked in acceptance report.
R15 Partial: Kaliningrad tenant config read back and skill delivered; owner acceptance pending.
All worker patches integrated as separate commits; root owns final tests, runtime and report.
No unmerged writable work is intentionally abandoned; MAX/main/unrelated production remain out of scope.
