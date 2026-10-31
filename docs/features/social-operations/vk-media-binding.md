# VK photo identity binding

Status: **Fixed** product decision D8 / §18.1 (2026-10-27); implementation is **Not confirmed by user** until live acceptance.

A successful `photos.saveWallPhoto` returns a native photo ID. VK may copy a user-owned upload to the community wall and change the final IDs or bytes. For an **exact known wall/postponed post ID and target**, trust the ordered provider attachment IDs; bind them to the ordered frozen asset SHA-256 values with `native.bind_media`. Source hashes describe the frozen inputs, not bytes later served by VK. Do not fetch VK CDN renditions, calculate fingerprints, persist `photo_proofs` or require source/final photo ID equality.

The adapter reads the exact post where possible, checks target, namespace, attachment type/count, text and requested time. User-upload → community-copy remapping is valid. A small difference in text/schedule or remapping is reported through the existing progress warning, **not** as a manual-review outcome. With a known ID and temporarily unavailable readback, return the same published/scheduled outcome from the frozen request and ID, with one warning. A scheduled item has no public wall permalink; a published item uses `https://vk.com/wall{owner}_{id}`. Never invent a scheduled public link.

Persist ordered saved IDs immediately after each `photos.saveWallPhoto`, including scheduled posts. Do not store `access_key`, private upload URLs or CDN metadata. The selected prefix is scoped to one plan/target and exact frozen ordered assets. Later edits explicitly preserve observed attachments: VK wall.edit may clear attachments when omitted. No additional `photos.getById` permission or byte-proof step is required.

Earlier native lifecycle checks demonstrated VK copy remapping and the need to retain attachments on wall.edit. Their historical SHA/CDN proofs do **not** remain a requirement for new publications. Live acceptance and ordinary native authorization, CAS and no-duplicate guards remain separate.

## VK in-place colourization and retention (2026-10-31)

Status: **Not confirmed by user** until Opus review, rollout and live VK acceptance.
For `vibepublish_publication_update` by a fresh `item_ref` (exact `vibepublish_read`
item read), a VK published **or postponed** post accepts an ordered edit `media`
list consisting of freshly imported assets and
`{"source":{"kind":"existing","position":0}}` references. The position indexes
the ordered native `provider_media` IDs of **that exact post**. For example,
`[new_colour_asset, existing_position_0]` maps to
`wall.edit(attachments="photo<new_id>,photo<original_id>")`; original bytes,
CDN downloads and hashes are neither requested nor retained. CAS checks the
same remote content/attachments again before editing. Unmanaged posts are
eligible within an already authorized destination; provider linkage is not
ownership of another user's private assets. Plain text-only VK edits preserve
the remote attachments and need no old local asset data.

A VK permalink `https://vk.com/wall-OWNER_ID` can be read as an exact native
item **only if OWNER is already bound**. A VK publication originally queued
under a different native postponed ID must be read again in the published feed
and changed by that new `item_ref`; the Telegram-oriented
`native_item_published` revision guard is not bypassed. Scheduled edits
retain the existing 60-second native lead/CAS guards. Telegram's managed
single-media edit and MAX limitations do not change.

Local `assets` bytes are transient for all three providers: text-only edits and
reschedules use exact observed native attachments instead of old image bytes.
An explicit `edit.media: []` is refused rather than silently removing media.
Unsent work older than three days after `max(created,scheduled_at)` is closed
without provider dispatch (`stale_not_dispatched`). Failed and uncertain effects
retain their immutable receipts, but only keep asset bytes for three days after
the last worker observation; an already unknown effect is never replayed.
The existing explicit `retry_failed` and `supersede_failed` paths also refuse
expired never-dispatched public intents, even with no retained asset bytes.
The private Telegram media-store recovery horizon is unchanged.
Preview operations awaiting approval retain their photo bytes for up to three
days; no preview may lose its input immediately after preflight.
Unlinked uploads and visual candidate/derivative media expire after 14 days;
expired visual candidates, their origin and feedback references are removed
alongside the binary while the visual job and its text remain. Waiting VK-linked
Stories remain protected. Emoji catalog metadata and assets are unchanged.
`media_store` staging and one-hour `download_cache` retention, list/get,
asset preview and `GET /v1/assets/{id}` are unchanged.
The source tree provides a read-only-by-default SQLite dry-run command,
`python scripts/inspect/vk_asset_retention.py --db PATH`. The `--apply`
deletion + VACUUM is reserved for explicitly approved coordinated rollout.
