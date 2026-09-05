# Continue VibePublish: one module remains to be delivered

Work personally in ChatGPT; preserve PR #1, its code and tests. No new MAX task,
live provider/model call, deployment or merge is authorized by this handoff.

Repository: `onedayonemasterpiece/vibepublish`.
Branch: `work/vibepublish-core-20260904`.
Read [current runtime status](../operations/social-runtime.md), then fresh-read
PR #1/#2 and their actual HEADs. Source commit `ae73b259ddf60c80875c285d3e5c9d51723ce3f0`
delivered the unchanged rich-text compiler and VK adapter. Do not repeat those
implementations. Later documentation commits may advance the branch.

Only `adapters/codex_imagegen.py` remains absent. A new full-file tree request
received an explicit request-safety-evaluation block; no alternate upload was
used. Respect that outcome. Ordinary independent writes succeeding does not
prove delivery or permit routing that effect through encodings, split files,
another tool, CI, an archive bootstrap or an agent.

The complete reference is the existing `vibepublish-sdk-locked-20260905.zip`,
SHA-256 `179b101877e10c8d37606a4156a4de35e19cda6f127a26181553537623a5c40c`.
It contains 133 source files and 203 payload hashes. Verify bytes with VERIFY.py;
retain current branch docs rather than applying its old base patch wholesale.

On the delivered tree, real Telethon/core compilation passes all 14 wire cases.
Strict collection finds 296 tests and one missing-Codex-module import error.
Diagnostic execution with --continue-on-collection-errors gives 296 passes and
199 subtests, but still exits 1. The 31 Codex-process tests cannot collect. Do not
call this full green CI or weaken the mandatory checks.

After permitted full delivery, require exact remote source readback and the
unchanged full Python 3.12/3.13 hosted workflow. Then verify the installed local
Codex ON DEVCOVEER through a callable non-agent host interface: actual CLI/skill,
image-only controls, exact generated files and structured events. Scripted CLI
results and operator booleans are not installed-host evidence. Keep provider
credentials, real-generation budgets, live tests and deployment separately gated.
