# Continue VibePublish in ChatGPT: delivery, Telegram emoji, DevCoveer imagegen

Work independently in ChatGPT through GitHub and local execution. Do not delegate
core, Telegram/VK, MCP, VisualService or emoji implementation to coding agents.
MAX is already assigned separately in PR #2; do not launch it again or create a
second MAX driver. No production deployment, EventsBot migration, live social
write, imagegen/MAX canary or credential copying is authorized by this handoff.

Repository: onedayonemasterpiece/vibepublish.
Continue `work/vibepublish-core-20260904`, draft PR #1. Do not create a replacement
branch/runtime, reset, force-push, or overwrite concurrent changes.
Fresh-read main, core HEAD/diff and PR #1/#2 including comments. Last read main:
`1ceb1cee2acd867c88f6e94a2815e78e816374fa`; pre-handoff core:
`49efec417e0605b95979ed3a3eebd1c0eb3bade8`. These are checkpoints, not frozen refs.

## Input must be actual bytes, not a filename in a prompt

The single ChatGPT transfer package contains this handoff, the emoji design and
an unchanged inner `vibepublish-native-visual-20260905.zip` (875577 bytes).
Inner ZIP SHA-256:
`5651e09a046806b0bfd1fcfb7a92998c22fd9e1c902e1d7f28b53db5fdbe1933`.
On receiving the package, list real mounted files and extract safely. Check all
103 source hashes and patch hash in the inner MANIFEST.json before editing.
Previous-file library references are not mounted bytes; obtain the actual file
before treating a library search result as a local path.

Inner LOCAL core HEAD: `870e2a4304c57ef5dd7152de63df1db6431a942b`.
Patch base: `60712c41cee5975c24c4e5346b22857f39c035ec`.
Patch SHA-256: `0b5ce0ca814e97e89e33714748a25a9f3a47e450bbcd0c33d566f1d7e327bff6`.
Read inner README_DELIVERY.md, VERIFICATION.md and
`source/docs/operations/social-runtime.md`. The archive is existing implementation,
NOT evidence it reached GitHub. Do not rewrite it from the older seed.

The earlier core tree write was blocked by OpenAI before that tree SHA, not by a
GitHub 401/403. Separate later documentation/inventory writes succeeded. Exact
block cause is unknown. Do not evade the block through alternate tools, encoding,
chunking, CI or MAX. When an authorized delivery path is available, transfer only
the missing delta, preserve newer docs and verify remote SHA/key files. A local
commit or unreferenced tree is not remote delivery. Otherwise retain a tested
applicable patch and describe the blocker; do not consume the window re-auditing
or declare the existing runtime complete on remote.

## First completed development package

Read current AGENTS.md, README, docs/README, docs/routes and canonical
social-operations/visuals docs plus
`docs/features/social-operations/telegram-custom-emoji-v1.md`.
Assemble a local tree that combines existing archived core and later remote
changes without wholesale replacement; inspect conflicts in docs/CHANGELOG/CI.
Reproduce tests using the lock:

```bash
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest tests -q
```

Earlier archive evidence is 168 passed + 199 subtests, zero failures/skips, plus
21 later inventory tests in remote CI. Those are prior results, not this window's
results. Clean lock install/full runtime CI remain unverified. Optional Telethon
SDK compatibility also remains a gate. Do not weaken tests or mislabel a timed
out run as passed. Use one GitHub-hosted CI; no self-hosted runner.

Implement a complete bounded Telegram custom-emoji slice in the existing core:
set metadata catalog, numbered real-media preview, revision-bound selection of
one emoji or ordered chain, personal reusable alias/rules, pre-send deterministic
rich-entity compilation, frozen approval/CAS and exact semantic native readback
for now/scheduled. Eight MCP tools remain eight; update closed schema/scoped
variants/get_started/skill with implementation, not invented calls.

Use E01-E12 from the canonical emoji design, especially the actual Tretyakov
wrong-pair regression, variable UTF-16 spans, formatting preservation, private
catalogs and sequence immutability. No delayed “send ordinary then fix later”.
Read actual donor `events-bot-new` current main; previously inspected
`b8f463f5c35fa62befcfed171a7a8a0886af20f7`, `tg_premium_emojis.py`, its tests/skill
and incidents. No EventsBot runtime dependency or credentials.

## Next package: actual image executor is LOCAL CODEX ON DEVCOVEER

The owner clarified the host: Codex is installed ON THE DEVCOVEER SERVER and
image_gen already works there. Do not ask for a probe on the owner's computer or
choose a third-party OpenCode package as a substitute. Required path:
VibePublish on DevCoveer -> local Codex image-only invocation -> actual result
file -> existing ImagegenExecutor/importer/VisualService.

Calling Codex only to generate an image is not delegating development to Codex.
Do not start a general coding-agent task to implement this integration. Inspect
actual host CLI/version/skill/tool schema through callable authorized DevCoveer
operations, without dumping auth. If tools are not exposed, report that narrow
host-access limitation, not that local execution is impossible. Implement/test
bounded process transport with a scripted CLI in ChatGPT; do not present this as
proof of the installed host's behavior.

Use actual CLI/event contract, explicit job workspace/verified source assets,
minimal available route and durable submit-before-effect/checkpoints. No guessed
CLI switches or fabricated model IDs. Collect exact returned file/event evidence;
never pick the latest unrelated image under generated_images. Separate requested
orchestrator route, actual host backend and actual image model where reported.
Kill/timeout/restart cannot blindly resubmit or be presented as upstream durable
inspect/cancel APIs. Keep existing budgets, lineage, artifact validation and one
parent continuation. No Google/API-key fallback without an owner change.
Real generation canary remains separately gated; coding/testing needs no canary.

## Parallel MAX status and coordination

PR #2 branch `work/vibepublish-max-web-20260904` at last read
`d0bceb2efd1ab2da83e6553a61f1a33b31a7b755` has 14 changed files and a synthetic
Chromium fixture driver; CI 33947076136 is successful (37 MAX + 22 contract tests).
Actual provider bridge and core/MCP integration were blocked because the archive
was NOT available in that Codex task. Reattaching the inner ZIP to that SAME task
is required; a sandbox link or mentioned filename does not deliver bytes there.
There is still no production MAX factory or observed live MAX selector set.
Read `docs/operations/max-web.md` in PR #2; do not equate fixture success with MAX.

Shared port: inner `adapters/port.py`; latest changing LOCAL commit
`25de851b911d02fc9ece2a7e193743758bfa48c1`; SHA-256
`4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0`.
It includes native_target/provider_media/member_ids and awaitable hooks. Coordinate
any additive rich-entity observation changes with PR #2, preserving compatibility
or a versioned migration; do not copy the port into MAX or add another ledger.

## Remaining product gates and reporting

Do not drop Telegram/VK multi-member lifecycle, full rich content, media/video/
stories, discovery/analytics, asset ingress, OAuth/TLS/production wiring and the
other explicit gates in the archived runtime/provenance docs. Deliver in bounded
packages; do not promise these are already implemented or all fit one window.
Keep native-only scheduling, source rights/native forwarding, partner scoped
queue reads, durable dispatch and per-destination early events unchanged.

Each completed package: code + real tests + canonical docs/routes/CHANGELOG,
small commits, remote readback and actual CI result where writable. At the window
boundary give exact branch/local-versus-remote SHA, commands/counts, offline vs
SDK vs live evidence, MAX port version, and one next implementable package. Save
an updated single transfer package with actual source bytes if any remain local.
