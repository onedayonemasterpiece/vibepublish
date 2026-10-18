# INC-2026-10-18-main-deploy-dropped-street-story-original-frame

Status: `Resolved` (2026-10-18)

## Summary

On 2026-10-18 09:05 UTC VibePublish was redeployed from `main` (`74a077b`, local media-store
archive for RKB, #82). The previously running release `ef3d8ba` came from the unmerged branch
`chatgpt/street-story-source-frame-20261014` (PR #80), which added original-aspect
standalone visuals for Street Story. `main` did not contain those commits, so the redeploy
silently rolled them back.

## Impact

- Every Street Story visual uses the original-frame contract (`original-art-aspect-v1`); new
  generations failed with `vibepublish_visual_error` (Street Story stories for photos 131, 120, 102
  stayed without an image, `needs_review`).
- `vibepublish_status` returned HTTP 500 for operations created before 09:05: the output schema of
  `74a077b` allows candidate `format` only `post_4_5` / `story_9_16`, and the stored receipt has
  `original` (`jsonschema` `oneOf` failure in `social_operations/service.py`). Street Story's Live
  `generate_visual` then failed with an uncoded `LIVE_TOOL_ERROR` (story 105).
- No publication was sent; Telegram and VK publishing were not affected.

## Timeline

- 2026-10-15 02:35 — release `ef3d8ba` (PR #80 branch) deployed for Street Story through the
  drop-in `zzzzzzzzzz-street-story-map-facts.conf`; PR #80 stayed open.
- 2026-10-18 09:05 — release `74a077b` from `main` deployed through the later drop-in
  `zzzzzzzzzzzzzz-local-archive-20261018.conf`, overriding the previous one.
- 2026-10-18 09:10–10:28 — Street Story visuals for 131, 120, 102 fail; status of the 105 visual
  returns 500 (three ASGI exceptions logged).
- 2026-10-18 10:30 — root cause identified from the VibePublish traceback and the release lineage.

## Root Cause

Production ran a feature that lived only in an unmerged branch. The next deploy from `main` had no
way to know about it, and nothing checked that the new release contains the commits of the
running one.

## Fix

- Merge `main` into PR #80, verify, merge PR #80 into `main`, deploy VibePublish from that `main`.
- Process: production is deployed only from `main` (or a release whose commits are all in `main`);
  before a deploy, the running release must be an ancestor of the candidate, otherwise stop.

## Regression Checks

- `vibepublish_status` for an existing `original` candidate returns 200.
- A new Street Story original-frame visual completes.

## Release Evidence

- PR #80 (with `main` merged in) merged into `main` as `6758a05`; full non-browser suite 1770 passed,
  browser suite identical to clean `main` (needs a live MAX browser); CI 6/6 green.
- `check_release_lineage.py --candidate 6758a05`: both units ran `74a077b`, contained in `6758a05`.
- 2026-10-18 ~11:30 UTC: `vibepublish` and `vibepublish-worker` restarted on
  `releases/6758a05…/source` (process cmdline and `PYTHONPATH` read back); no ASGI exceptions after restart.
- Verified on the product: Street Story 105 got a new original-frame visual (`op_6cae28cc…`, verified);
  120 and 102 got new visuals after Street Story deployed its fix for requests refused during the
  regression (Street Story PR #264, now also running from its `main`).

Retained evidence: `/home/dev/artifacts/vibepublish/20261018T103745Z-street-story-original-visual-regression-20261018/`
(traceback, affected stories, the overriding drop-in).

## Follow-Ups

- Done: lineage guard and the main-only rule in `docs/operations/production-runtime.md` and in the
  server-wide `/home/dev/AGENTS.md`.
- Done: Street Story moved its production to `main` as well (it ran from a chain of unmerged branches).

