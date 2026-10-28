# Resume VK photo staging

Status: **Fixed** owner policy D8 / §18.1; **Not confirmed by user** until live acceptance.

A never-dispatched VK wall publish/edit can reuse the existing `vk_photo_staging` checkpoint after an authorized retry or worker restart, **including native scheduled publications**. A separately authorized later edit may reuse a complete compatible prefix of the same managed post. The worker selects only compatible attempts and preserved authority; the adapter checks target, existing post, ordered frozen asset hashes, non-duplicated native photo IDs and their count. Other publications, changed assets, stale authority and already-dispatched attempts cannot lend photo receipts.

Write the prefix immediately after **each** successful `photos.saveWallPhoto` (not after a CDN read). A complete prefix needs no further upload or save. With a partial prefix, upload only the missing suffix in the original order. Accept user and community photo owner IDs; `photo_proofs` are neither stored nor required. Never persist `access_key`, signed upload URLs or private provider capabilities. If a particular saved ID cannot be reused without a transient access capability, restage that photo rather than storing or guessing the capability.

Existing pre-effect native baseline/CAS and dispatch fences remain. The final exact post is bound by ordered native attachment IDs and frozen asset hashes, not image fingerprints. A crash after provider save but before durable checkpoint may allocate the photo again; this is **not** a second wall.post. The existing idempotency key protects the public effect.

Regression: a ten-photo scheduled publish crashes after checkpoint #4, then reuses the first four saved IDs and uploads photos 5–10; total public `wall.post` calls: one. No new queue, cache, schema or recovery mode.
