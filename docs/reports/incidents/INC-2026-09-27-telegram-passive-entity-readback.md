# INC-2026-09-27 Telegram passive entity readback

Status: `Not confirmed by user` — source regression fix prepared; live provider
verification is required before closing the incident.

## Summary

An explicitly scheduled Telegram publication could reach the provider but
VibePublish then report `outcome_unknown` with
`telegram_entity_needs_review`. Native queue listing could fail with the same
error.

## Impact

The provider effect might already exist while VibePublish cannot prove the
native object. Retrying the publication would be unsafe because it could create
a duplicate. Queue inspection is also degraded until readback accepts the
provider's harmless inferred entities.

## Root Cause

Telegram can infer entities such as `MessageEntityHashtag` from plain text.
`from_native()` accepted only the subset of entity classes that VibePublish can
explicitly author. A provider-added passive span therefore failed readback even
though exact visible text matched.

## Fix

Keep the authored entity allowlist unchanged. During provider observation only,
ignore a bounded allowlist of passive span entities that carry no hidden payload.
Unknown entity classes outside that allowlist continue to fail closed.

## Regression Checks

- Offline Telethon transport: a plain-text hashtag receives a native
  `MessageEntityHashtag`, publication and reconcile stay read-only and succeed,
  and the provider-added entity is not promoted into authored rich content.
- Live acceptance: read the Telegram native scheduled queue and reconcile the
  already-dispatched 2026-09-28 21:00 Kaliningrad publication without resending.
