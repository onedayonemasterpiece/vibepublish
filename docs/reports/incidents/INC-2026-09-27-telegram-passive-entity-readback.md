# INC-2026-09-27 Telegram passive entity readback

Status: `Not confirmed by user` — source fix prepared; live provider verification is required.

## Summary

A scheduled Telegram publication containing hashtags could reach the provider while
VibePublish reported `outcome_unknown` with `telegram_entity_needs_review`.
Native scheduled-queue reads could fail for the same reason.

## Impact

The provider effect may already exist while VibePublish cannot prove the native
object. Retrying such a publication is unsafe because it can create a duplicate.
The connection can also remain quarantined, blocking subsequent scheduled work.

## Root cause

Telegram infers entities such as `MessageEntityHashtag` from plain text.
`from_native()` accepted only the entity classes VibePublish can explicitly author,
so a harmless provider-added span caused readback to fail despite exact visible text.

## Fix

Keep the outbound authored entity allowlist unchanged. During provider observation,
ignore only a bounded allowlist of passive span entities carrying no hidden payload.
Unknown native entity classes outside that allowlist still fail closed.

## Regression and live acceptance

- Offline Telethon transport covers a plain `#Калининград` caption receiving a
  native `MessageEntityHashtag` and verifies execute/reconcile stay single-effect.
- Live acceptance must read/reconcile the already-dispatched 28 September 2026,
  21:00 Europe/Kaliningrad item without resending it, then verify ordinary native
  scheduled-queue reads succeed.
