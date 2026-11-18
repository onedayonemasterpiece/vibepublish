# INC-2026-11-18-vk-credential-mapping

Status: `Open`; source repair is not live publication acceptance.
Registry: `inc_b2965bcf2daea3a6471b5e3e`.

## Summary

The owner's Telegram/VK postponed post failed preview while VK used a valid
credential without the required publishing scope. The owner requested a permanent
repair using the updated existing env credentials.

## Impact

The requested 18 November 19:00 Kaliningrad publication was not scheduled.
No provider write was attempted by the failing preview
`op_8866dcf9b67441cbbc4438c9d4b8a286`.

## Timeline

- Env file modification: 16 November 08:53:26 UTC.
- Worker startup: 18 November 16:36:45 UTC; selected `VK_USER_TOKEN3`.
- Read-only provider probes on 18 November: selected key has permission mask
  `65536`, `can_post=0`; existing key `VK_USER_TOKEN1` has mask `135211230`,
  `is_admin=1`, `admin_level=3`, `can_post=1` for community 241261191.
- `users.get` verifies both keys represent the same user. No credential values
  are recorded. Source mapping repair is isolated from the concurrent PR245 rollout.

## Root Cause

The deployed explicit key selection no longer provides the destination's
publication rights. The env already predates the worker, so this is not stale
in-memory credentials. Queue reads alone do not prove publishing permission.

## Fix

Select the verified existing key `VK_USER_TOKEN1` in the canonical worker unit
and installer validation. Keep explicit selection, no fallback or key guessing.
Synchronize the effective live drop-in through the coordinated runtime operator;
do not replace the running release or other provider flags to change one key.

## Regression Checks

The canonical unit assertion requires key1. The installer accepts that unit and
rejects replacement with the previous key3. Run the deployment suite before
source delivery. Test results are reported in the change receipt.

## Release Evidence

Live config activation, read-only provider-backed preflight and delivery of the
missed post are tracked separately. This document does not claim them completed.
No publication is performed by this source task.

## Follow-Ups

Verify effective key1 after the concurrent worker release. Recheck the same
post's per-target preview; the parent preview error alone is not evidence of an
independent Telegram failure. Confirm a new schedule with the owner before any
publication, because the original requested time has passed.
