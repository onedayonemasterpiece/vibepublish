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
