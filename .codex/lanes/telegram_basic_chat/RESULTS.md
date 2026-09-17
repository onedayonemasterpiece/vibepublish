# Basic-chat creator publication lane

Status: implementation/offline verification **Not confirmed by user**;
live canary **Not done** in this lane.

## Scoped change

The existing `_rights` unconditional Telegram group mutation rejection now has
one narrow exception: exact active/unmigrated basic `Chat`, native `creator is
True`, matched non-bot `mtproto_user`, new immediate `post`/`publish`, no existing
item, schedule or forward source. It does not interpret broadcast post_messages
as group permission. `_rights` is called at inspect/prepare and again before
execute uploads/effects, so a creator role lost after preflight blocks execution.

Megagroups, placeholders, non-creators, bot accounts, left/kicked/migrated/
deactivated chats, native group schedules and group edit/delete/forward/cancel/
reschedule remain gated. No core, ledger, worker, schema, secret or live social
object changed. No existing tests changed. Root owns integration and changelog.

## Research

Current Telegram chat constructor says creator is the current user's ownership
flag; migration contract requires new messages target the supergroup, which this
adapter deliberately does not follow. Telethon 1.44 documents creator permissions
and broadcast-only post_messages semantics. Canonical provenance document links
all primary sources. No fixed requirement forbids this limited capability; the
former gate was an implementation limitation.

## Verification

- New 25 offline cases + existing native-adapter tests: `70 passed in 1.75s`.
- Complete providers directory: `89 passed in 5.00s`.
- Compileall of changed adapter/new tests passed; git diff --check passed.
- Positive tests preserve exact PeerChat target, text, media hash/order,
  before-effect marker and zero preflight mutation/upload.
- Negative tests include all retained capability gates, source-smuggling,
  explicit boolean creator and rights revoked before execute.
- One offline test constructs the actual installed Telethon Chat type.
- No live RPC, personal session, publication, deployment or push performed.

## Integration

This is a separate commit after the already integrated `cf2df31`; do not replay
that earlier Imagegen commit. Cherry-pick only this lane's new commit. The only
runtime code change is in `adapters/telegram.py`; root's native_worker.py remains
untouched. Live acceptance must still confirm the authorized destination and
exact provider IDs/content before any success claim.
