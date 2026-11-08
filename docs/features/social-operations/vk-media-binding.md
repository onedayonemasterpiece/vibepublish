# VK photo identity binding

Status: **Fixed** product decision D8 / §18.1 (2026-10-27); implementation is **Not confirmed by user** until live acceptance.

A successful `photos.saveWallPhoto` returns a native photo ID. VK may copy a user-owned upload to the community wall and change the final IDs or bytes. For an **exact known wall/postponed post ID and target**, trust the ordered provider attachment IDs; bind them to the ordered frozen asset SHA-256 values with `native.bind_media`. Source hashes describe the frozen inputs, not bytes later served by VK. Do not fetch VK CDN renditions **for publishing, verification or attachment binding**, calculate fingerprints for publication proof, persist `photo_proofs` or require source/final photo ID equality. A separate owner-authorized **exact item read** may fetch a photo rendition as an editing input (see below); its byte SHA describes only the downloaded bytes and is never compared with an uploaded source or CDN hash.

The adapter reads the exact post where possible, checks target, namespace, attachment type/count, text and requested time. User-upload → community-copy remapping is valid. A small difference in text/schedule or remapping is reported through the existing progress warning, **not** as a manual-review outcome. With a known ID and temporarily unavailable readback, return the same published/scheduled outcome from the frozen request and ID, with one warning. A scheduled item has no public wall permalink; a published item uses `https://vk.com/wall{owner}_{id}`. Never invent a scheduled public link.

Persist ordered saved IDs immediately after each `photos.saveWallPhoto`, including scheduled posts. Do not store `access_key`, private upload URLs or CDN metadata. The selected prefix is scoped to one plan/target and exact frozen ordered assets. Later edits explicitly preserve observed attachments: VK wall.edit may clear attachments when omitted. No additional `photos.getById` permission or byte-proof step is required.

Earlier native lifecycle checks demonstrated VK copy remapping and the need to retain attachments on wall.edit. Their historical SHA/CDN proofs do **not** remain a requirement for new publications. Live acceptance and ordinary native authorization, CAS and no-duplicate guards remain separate.

## Prepared worker media reuse (2026-11-08)

Status: **Not confirmed by user** until worker rollout and live verification.
A successful preflight freezes its verified media bytes in the existing immutable
`Prepared.request`. Execution reuses that request after the existing source-link
binding/epoch/right check, avoiding a second full BLOB load and hash of every
attachment. The asset-update trigger and pending-operation retention protect the
saved inputs. First preparation, reconciliation without a prepared request and
finalization retain their existing reads and integrity checks. Actor/binding
authority, revision admission, lease/fence, deadlines and before-effect dispatch
CAS remain unchanged. Real Store/native-adapter regressions distinguish duplicate
reads and check source-grant revocation after prepare, before upload. This source
fix does not establish the cause of the observed worker OOM or a live memory bound.

## Missing scheduled response correction (2026-11-08)

Status: **Not done** until rollout and live verification. Night r6 received explicit
VK 214 refusals, then an older post with the same text, time and photo count was
mistaken for the new publication. That receipt is not delivery evidence.

An explicit VK 214 add-post refusal uses the existing `provider_access_denied`
outcome and must not repeat `wall.post`. When its response ID is missing, a queue
candidate must uniquely match the nonempty, ordered saved native photo IDs as
well as the frozen text/time. Text/time/count or the newest numeric post ID alone
cannot establish identity. Otherwise the existing same-`guid` path obtains the
authoritative post ID before any copied-photo binding. Known response-ID
acceptance stays unchanged; no CDN or source/output byte comparison is added.

### Withdraw a contradicted local receipt

An owner may use the existing `publication_update(change.kind=reconcile)` with
the original publication/revision, operation/attempt IDs, a request key and
`native_reference` from a fresh exact provider item read (at most 300 seconds
old). For this narrow legacy case, the scheduled VK publish must retain an
unresolved-ID `vk_prepared` origin and a final copied-photo observation. A
same-owner, same-binding/epoch publication must have verified that same native
post and ordered attachments before the newer intent existed; its existing fact
must still identify the older publication. The two immutable plans must have
different ordered source asset hashes; no CDN bytes are compared. Text, schedule, count and missing
diagnostic events are not sufficient evidence.

The correction performs no provider call. In one local transaction it withdraws
only the newer attempt's false item/queue references and current delivery
identity, retaining the former observation, original checkpoint, immutable
intent/plan and dispatch marker as audit. The original operation becomes
`outcome_unknown`, `retry_safe:false`, with `next_action:review_outcome`.
Existing facts and the older publication and fresh read references are unchanged.
The same correction key only replays its receipt. A durable withdrawal marker
blocks subsequent reconcile admission; retry/supersede/repeat, selected edits
and removal resolution cannot use the withdrawn identity to produce an effect.
This does not establish that the newer publish had no effect or authorize
deleting the older post. Status: **Not confirmed by user** until rollout and
the exact incident correction are verified separately.

## VK exact item photo source reads (2026-10-31)

Status: **Not confirmed by user** until Opus review and rollout. Published and postponed `read(kind=item)` may return photo downloads through the existing verified-asset read pipeline (`item.media[*].source` and full-resolution MCP/HTTP asset reads). Use the response's `orig_photo` URL where available, otherwise the largest `sizes` rendition; no signed URL/access key is stored or logged. This is an editing source, **not** publisher upload/proof data. A CDN error leaves the item's text, schedule and fresh `item_ref` readable with one `media_download_unavailable` code; `existing.position` continues to refer to original native VK attachment IDs. A postponed ID no longer in the native queue resolves to no item (never to the next queued post); a subsequent edit refuses with `remote_item_missing`. Scheduled/feed list scans never download images. Exact VK photo reads use the existing single-copy, one-hour `media_store_assets.download_cache` and its normal cleanup, **not** the 14-day unlinked upload retention. Asset reads enforce expiry for the requested asset without acquiring a SQLite writer or purging unrelated assets; unfinished operations, saved carousel revisions and exported cards retain their existing holds. The same expiry rule governs the existing worker's physical cleanup and carousel original selection, so expired unheld bytes remain unavailable while cleanup is pending and an expired cache copy cannot shadow a durable same-owner alpha source. The 14-day retention remains unchanged for other assets.

Native photo verification, SHA/type/size binding checks and image sanitization run before the worker acquires the SQLite writer for read completion. Source-cache preparation retains dimensions rather than unused sanitized image copies. The commit still rechecks the worker fence, current actor and binding, and any private entry grant/download proof, then atomically saves assets, facts, item references, cursors and operation completion. Unrelated carousel renders can record their journal while photo verification is running. A local `native_read_media_prepared` diagnostic records only the operation ID, download count and preparation duration; it does not expose provider URLs, native IDs or image bytes. This source behavior is **Not confirmed by user** until the changed worker is deployed and the concurrent native-read/render path is verified live.

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
asset preview and `GET /v1/assets/{id}` are unchanged. Pending operations
retain their input bytes until a terminal outcome; an absent required copy is
reported as `asset_expired` with an instruction to reupload, separately from
`asset_integrity` for corrupted bytes.

Maintenance cost and cadence (2026-11-08): **Not confirmed by user**. Global
cleanup deduplicates saved `(tenant, principal, asset)` references before joining
same-owner original PNG/WEBP dependencies. Every immutable carousel revision,
direct asset reference and exported card remains a hold; expiry classification
and deletion stay in the existing atomic transaction. This prevents asset count
and repeated revision references from multiplying the source lookup work.
Worker lanes using the same Store share the existing 60-second deadline after
successful cleanup. Constructing another lane does not reset it; a failed
transaction and an explicit single-operation tick do not advance it. This is
in-process cadence sharing, not coordination between separate Store instances
or processes. Real Store regressions bound SQL work and preserve source/alpha,
expiry and failure behavior; rollout and live contention verification remain
separate.

Residual writer latency (2026-11-08): **Not confirmed by user**. Post-rollout
maintenance still held the writer for 8–10 seconds, and one saved-region writer
held it for 3.5 seconds. A bounded disposable image fixture showed that the
owner/hash lookup traversed wide asset rows; a nonunique metadata-only index
now serves the existing source join and deduplication predicates without changing
owner, hash, MIME, dimension, newest-created ordering or quota rules. Store
initialization creates it additively and idempotently at the existing schema
version. Its first build scans existing metadata and takes a writer; the small
fixture's build time is not a production startup bound.

Successful slow maintenance and saved-region transactions also emit fixed phase
durations after connection release. Maintenance reports expiry, cache purge,
retention classification and reclamation. Saved regions report authority,
hashing, deduplication, quota, byte insertion and journal work; quota/insertion
are marked not run on a deduplication hit. Timers start after writer acquisition.
The separate `tx_exit_ms` includes commit, connection close and the existing
Store diagnostic handler, so it is not pure commit time or exact writer hold.
Diagnostics are best effort, contain no SQL, identifiers or payloads, and do not
change the successful cleanup deadline or receipt. The actual dominant live
subphase remains unproven until these phases are observed after rollout; the
source profile alone does not close the live latency incident.

Carousel export diagnosis (2026-11-08): **Not confirmed by user**. A real
post-rollout export recorded 56.144 seconds, but maintenance/saved-region phase
logs do not cover export. Each newly committed export now emits one bounded
`carousel_export_phases` diagnostic after writer release. Wall and calling-thread
CPU durations separate admission entry/work, source resolution/validation,
cache/render, slicing, image verification, persistence entry/work and transaction
exit. Entry intervals include connection/setup and BEGIN acquisition, not only
lock wait; exit includes commit, close and existing Store diagnostics. Thread CPU
does not include separate native/other threads. Total time ends before the new
diagnostic handler, receipt read and transport; the existing journal duration
boundary is unchanged. The cache flag and aggregate
unique composition-source/master/slice/verified byte counts use already available
data, with no extra asset reads. Immediate/late replays and pre-commit failures emit
no new completion record; observer failures cannot change the receipt. No private
IDs or payloads are logged. This diagnoses the next real export; it does not
establish the dominant live phase or claim a speed improvement.

VK feed and queue reads preserve unsupported attachments (poll/link/market and
unrecognized payloads) as opaque `unsupported:kind:owner_id` identities instead
of blocking the read. Because `wall.edit` would erase such attachments, edits and
reschedules are refused **before native effects** with
`vk_attachment_edit_unsupported`. Their existing post identity and other reads
remain available.
The source tree provides a read-only-by-default SQLite dry-run command,
`python scripts/inspect/vk_asset_retention.py --db PATH`. The `--apply`
deletion + VACUUM is reserved for explicitly approved coordinated rollout.
