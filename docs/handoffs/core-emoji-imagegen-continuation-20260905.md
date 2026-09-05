# Continue VibePublish from verified remote source, not a stale summary

Status: **Not confirmed by user / partial source delivery**.
Work personally in ChatGPT. Preserve the existing implementation and PRs.
No delegated coding, deployment, merge, live social write or model invocation is
newly authorized by this handoff. MAX stays in its existing PR #2.

## Start with the real state

Repository: `onedayonemasterpiece/vibepublish`.
Branch: `work/vibepublish-core-20260904`, draft PR #1.
The five source commits through `18152e5d7bbc5ebe2d5e04006b0563ab8de9fb2e`
are real. A prior ChatGPT final response incorrectly said they did not exist.
`76ad2c554fe5866ddd23f79154095d281e099154` subsequently attached ten documentation
changes from the already accepted, read-back tree
`1f36d7259bf52d2ca53f54e4bffbee071a103d91`. The earlier failed tree/commit attempts
are not evidence that this exact tree is unavailable: its GET and commit worked.

Fresh-read PR #1/#2, the branch commit/tree and
[canonical runtime status](../operations/social-runtime.md). Do not report the
old `c1d0cede` or `73345b4` as the current HEAD merely because old prose names it.
Do not repeatedly rediscover a loaded tool instead of invoking its schema.
Use exact returned tree/commit IDs; a local prediction is not a remote object.

## Actual remaining implementation

Only three runtime modules remain absent from the archive's source set:
`adapters/vk.py`, `social_operations/rich_text.py`,
`adapters/codex_imagegen.py`. Each received a recorded request-safety-evaluation
block earlier. No new failure or release permission is inferred from this text.
Do not re-encode, split, proxy through another tool/agent, upload an archive to
execute on CI, or replace the implementation to obtain a denied write effect.
A historical error does not make every independent operation forbidden; new
independent work must still be checked by its real response and readback.

The complete source is retained in `vibepublish-sdk-locked-20260905.zip`, SHA-256
`179b101877e10c8d37606a4156a4de35e19cda6f127a26181553537623a5c40c`.
It has 133 source files and 203 payload hashes. Verify bytes with `VERIFY.py`.
Use it as the missing-source reference, never blindly replace newer branch docs.
The full local HEAD is `8dcc771848051dab8b9bc7ae51f92a9757dfa7ef`;
that identity is not a remotely delivered complete application.

## Acceptance

The existing source, updated contract/skill 1.5, eight MCP tools, SQLite migration
3, native-only schedules, exact emoji selections/entities/readback, immutable
visual lineage and single parent continuation must stay intact.
All existing test files are now in GitHub. Do not weaken them to hide missing
imports. The current partial tree passes 69 independent tests + 199 subtests,
but full collection has 10 errors; core-aware SDK import fails. The historical
327 + 199 result belongs to the complete archived source, not this checkout.
The single hosted Python 3.12/3.13 workflow keeps its mandatory runtime gate.

After source delivery is genuinely complete, require exact source readback and
full hosted tests. Then verify the installed Codex **on DevCoveer** through an
available non-agent host interface: actual executable/version/skill, image-only
controls, exact job artifacts and structured events. Scripted CLI tests and
operator booleans are not host/canary evidence. No personal-PC, guessed OpenCode,
Google or API-key fallback. Keep original imagegen and live-provider gates open.
