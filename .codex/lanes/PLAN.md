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
