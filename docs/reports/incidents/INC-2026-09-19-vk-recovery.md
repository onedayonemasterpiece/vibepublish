# INC-2026-09-19-vk-recovery

Status: `Not confirmed by user` — VK feed and queue reads verified through public MCP.

## Summary

DevCoveer2 VibePublish initially had a verified Telegram read path but no VK
connection. VK is now connected and public MCP feed and queue reads pass.
Offline tests and MCP health checks alone were not sufficient evidence.

## Impact

VK reads were unavailable. Reads now pass; publications and other write effects
were not exercised or claimed by this recovery.

## Root Cause

Live MCP acceptance exposed `vk_read_target_mismatch`: VK returns a shared post
under its original wall identity, plus the requested wall's explicit approved
`coowners.coowner_post_id` mapping. The adapter did not resolve that mapping.
The adapter now resolves only a matching approved wall-local identity. Public
MCP feed acceptance includes the shared post and succeeds after this correction.

Provider recovery was left incomplete. The production worker supported either
Telegram alone or the full Telegram/VK/MAX topology, not an explicitly selected
Telegram/VK topology. Historical acceptance referenced `VK_ACCESS_TOKEN4`, which
was not found in the checked credential sources. The restored `.env` contains
multiple other VK tokens. The owner identified VK_USER_TOKEN and variants 1/2/3
as today's user tokens and requested checking them. Live read-only checks found
variants 1 and 2 matched the historical account and group admin level 3, and read
the wall. The base variable returned VK code 9; variant 3 returned VK code 5.
No expiration or invalidation cause is inferred from issuance date alone.

## Fix

Selected verified VK_USER_TOKEN1 explicitly; variant 2 is not an automatic
fallback. Registered devcoveer2-vk and the known lovekenig group (-241261191) as
lovekenig_vk for the existing owners. Switched only the VibePublish worker to
`--providers telegram vk` with in-memory credential mapping. No tokens were
created, copied, replaced or rotated; no social writes were performed.

## Regression Checks

Keep the default full topology strict; preserve Telegram session locking and
legacy Telegram-only configuration. Require selected providers exactly once.
Require a completed VK provider read before reporting VK recovery success.

## Release Evidence

Public HTTPS OAuth + MCP checks on 2026-09-19:

- VK feed: op_5ba5a9eaa4f84e409843ad8fd5afa860, verified, 3 provider items.
- VK postponed queue: op_147251cfa2de44ffa8a36a9a08fefc35, verified, 0 items.
- Telegram thread recheck: op_3843b2bc46044f649e4abef33fb38a3f, verified, 3 provider items.
- Verification-only OAuth grant revoked; existing grants untouched.
- Coowner, native adapter and deployment tests: 91 passed.
- Full provider, SDK and deployment regressions: 249 passed.
- Server and worker active; worker NRestarts=0 after activation.

Raw provider content, token values and OAuth credentials are not included in
this record. MAX and publication acceptance remain outside these PASS results.
