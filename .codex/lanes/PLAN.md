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
R03 Engineering verified: Telegram lifecycle/emoji/media and VK post10 full media lifecycle; owner confirmation pending.
R04 Superseded for runtime activation by ordinary-task R12; legacy source preserved.
R05 Partial: integrated local suite and public service evidence recorded; no full hosted CI claim.
R06 Partial: no-AI original ingress/readback verified; actual current chat attachment handoff not observed.
R07 Partial: prompt-first generate/tune/compose native images verified; composition fully queued, failed task histories retained.
R08 Superseded by explicit NOW as well as scheduled execute R13.
R09 Engineering verified: exact ordered provider bytes prove copied IDs; old8/9 unknown histories retained and explicit absence resolutions recorded.
R10 Partial: native image receipt/path/hash verified; not a hard billed-call attestation.
R11/R14 Partial: HTTP and real MCP file-object ingress verified, client UI handoff unverified.
R12 Partial: ordinary Luna tasks live, no API fallback; owner acceptance pending.
R13 Partial: automatic scheduled composition verified; no-time live evidence tracked in acceptance report.
R15 Partial: Kaliningrad tenant config read back and skill delivered; owner acceptance pending.
All worker patches integrated as separate commits; root owns final tests, runtime and report.
No unmerged writable work is intentionally abandoned; MAX/main/unrelated production remain out of scope.

## Completion continuation: VK copy binding and explicit recovery
R16 VK copied photo identities: root owns adapters/vk.py, vk_transport.py and provider tests; bind via verified pre/post provider image bytes, preserve order and no uncertain resend.
R17 resolve quarantined externally removed scheduled attempt: worker in separate agent/vibepublish-unknown-resolution worktree owns bounded new owner reconciliation action, core recovery/storage/contracts/migration/tests/canonical recovery document. No VK adapter or deployment writes; root integrates after R16.
R18 real crash/restart acceptance: root deployment-only exact-operation one-shot response-checkpoint hook, after R16/R17; never kill shared services.
R19 remaining ingress/client/host gates: root after functional acceptance, preserve original host and credential permissions.
Integration: R17 committed merge into root, combined tests, ownworker deployment, exact old VK resolution, new VK live lifecycle, crash canary, final evidence/push. No main/MAX/unrelated production edits.

R16/R17/R18 engineering verified: live post10 lifecycle, owner absence proofs for8/9, real post11 response-checkpoint SIGKILL/recovery/cancel; owner confirmation pending. R19 remains partial: current client handoff unobserved, shared renderer activation/TLS renewal unresolved. Worker R17 commits8035af7/d1a6270/7cfc7ee/7b806b4 all integrated; reviewer fixes included, no abandoned patch.

## ChatGPT readiness 2026-09-06
R20 OAuth ChatGPT authentication (missing, implement): dedicated worker high/security lane in separate agent/vibepublish-chatgpt-auth owns OAuth module, narrow server auth integration, auth tests and canonical auth doc. Root owns ownstand launcher/wiring, live protocol/browser acceptance, TLS and report. No publishing in this continuation.
R21 certificate renewal (unverified): root inspect existing hooks/timer, scoped lineage dry-run only; no unrelated certificates/credentials.
R22 durable shared renderer (pending scoped controller permission): root read-only until explicit answer; no watchdog/runtime injection.
R23 real ChatGPT client/file handoff: root protocol+browser checks, real account flow requires owner's UI action if no authenticated browser available; never claim synthetic file import is observed ChatGPT attachment transfer.
Integrate OAuth worker committed patch, run full existing suite and auth/browser tests, deploy only ownstand with owner-readable instructions; final public discovery/MCP evidence, commit and remote readback. Shared controller remains a separate scope.
