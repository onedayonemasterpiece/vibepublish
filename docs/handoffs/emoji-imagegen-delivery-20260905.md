> Historical archive handoff, not current branch status. Read
> [the current continuation](core-emoji-imagegen-continuation-20260905.md)
> and [runtime delivery status](../operations/social-runtime.md) first.
> Versions, counts and limitations below describe that earlier checkpoint.

# Continue the verified core + emoji + Codex-process source

Status: **Not confirmed by user**. Continue personally in ChatGPT, no delegated
coding/diagnostic agent. Preserve the existing implementation. No new live social
write, model inference, deployment or MAX task is authorized by this handoff.

## Actual inputs and delivery

The transfer package contains complete source, MANIFEST, verification logs,
applicable cumulative patch from the current remote tree and local Git history.
Verify every hash with VERIFY.py. Exact final local HEAD/tree are in MANIFEST.
Do not apply an old seed-based patch over newer remote docs/tooling.

Existing branch/PR: `work/vibepublish-core-20260904`, draft #1. At this checkpoint
real remote HEAD is `73345b450793b92dfa1f3992713b4b7d7541c9b2`, tree
`cdc6e61de490c7ba864eac5fe6f858853d0aba64`. New remote commits `ce3856db` and
`73345b4` deliver independent native SDK/dependency verification, lock, CI and
docs. The full core still is NOT in that branch. A local snapshot base has the
same tree but a different commit identity; do not label it a remote commit.
Fresh-read PR #1/#2/main and comments before making later changes.

Earlier full-core upload was stopped by OpenAI's request safety check, not GitHub
401/403. Its cause is unknown; this turn did not retry/bypass that protected
payload. Ordinary read/comment or independent tooling-write success is not an
unlock. Do not route the old core through another tool, encoding, chunks, CI,
MAX or another agent. Use only a permitted non-bypassing source-delivery path
when available; otherwise retain complete verified source without claiming push.

## Gates closed in this continuation

- Input archive: all 197 hashes, including 126 source files, verified.
- Real clean venv: 70 dependencies from a hashed GitHub-hosted wheelhouse, no
  system-site Python packages, no-index/hash-enforced install, pip check clean.
- Full suite: **327 tests + 199 subtests**, 0 failures/skips. Existing 292 tests
  unchanged; 19 real-SDK tests and 16 dependency-verification tests added.
- Actual Telethon 1.44.0, all 14 request types, compiler, exact native emoji IDs,
  varied UTF-16 spans, request resolution and binary responses of an offline
  state double. Text/photo/album, native queue, edit/reschedule/cancel, media
  preservation, wrong-ID readback, authorization refusal and read-only recovery.
- The old SDK gate was wrong: GetAppConfigRequest is valid at exactly 8 bytes.
  `scripts/verify/telegram_sdk.py` now requires complete TL roundtrip, not >8 bytes.
- Prior `annotated-types==0.8.0` failure was DNS; the actual wheel installed.
  Direct runtime pins remain unchanged; refreshed cssselect2 0.10.1 and
  webencodings 0.6.1 plus optional SDK/browser/build pins are explicit in the lock.

Inspect the package's current VERIFICATION.md for final replay/wheel/CI results;
do not inherit the above as a new execution claim. Primary operational document:
`docs/operations/dependency-sdk-verification.md`.

## Remaining work, not a repeat audit

First complete permitted full-source delivery into the existing PR and verify the
full-core workflow, not just the remote seed/SDK workflow. The local full-source
`.github/workflows/ci.yml` has mandatory application/Chromium/SDK/full-suite steps.
Keep it when integrating; no second or self-hosted workflow.

Then verify the installed local Codex **ON DEVCOVEER** using a callable non-agent
host metadata/read operation: executable/version, actual imagegen skill and tool
contract, image-only controls, dedicated profile/OS restrictions, structured
output/event and exact artifact paths. In this window plugin discovery reported
Codex DevCoveer installed, but actual tool discovery returned no such namespace;
there was no direct CLI/skill access. No start_task/continue_task was used. This
is a tool-exposure limitation, NOT evidence that imagegen is absent on the host.
Do not substitute the owner's PC, guessed OpenCode plugin, Google or API-key CLI.
The existing CodexImagegenExecutor stays disabled pending host evidence; its
scripted CLI tests are not installed-Codex/image-generation proof.

MAX is separate PR #2 and progressed independently. No MAX code/shared-port or
runtime adapter change was made in this continuation. The last fresh-read MAX
HEAD was `1a650dc21c391ef9459e48a1a3b48b5013ce6a8f`; refresh it rather than assuming
this is current. No new combined MAX+emoji test or live MAX claim is inherited.
Eight tools, contract/skill 1.5.0-runtime, migration 3 and native-only scheduling
remain unchanged. Read README, docs/README/routes and the canonical runbooks;
all provider/live/product gates not closed above remain explicit.
