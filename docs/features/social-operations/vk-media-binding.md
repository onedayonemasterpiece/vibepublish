# VK photo identity binding

Status: **Fixed** product decision D8 / §18.1 (2026-10-27); implementation is **Not confirmed by user** until live acceptance.

A successful `photos.saveWallPhoto` returns a native photo ID. VK may copy a user-owned upload to the community wall and change the final IDs or bytes. For an **exact known wall/postponed post ID and target**, trust the ordered provider attachment IDs; bind them to the ordered frozen asset SHA-256 values with `native.bind_media`. Source hashes describe the frozen inputs, not bytes later served by VK. Do not fetch VK CDN renditions, calculate fingerprints, persist `photo_proofs` or require source/final photo ID equality.

The adapter reads the exact post where possible, checks target, namespace, attachment type/count, text and requested time. User-upload → community-copy remapping is valid. A small difference in text/schedule or remapping is reported through the existing progress warning, **not** as a manual-review outcome. With a known ID and temporarily unavailable readback, return the same published/scheduled outcome from the frozen request and ID, with one warning. A scheduled item has no public wall permalink; a published item uses `https://vk.com/wall{owner}_{id}`. Never invent a scheduled public link.

Persist ordered saved IDs immediately after each `photos.saveWallPhoto`, including scheduled posts. Do not store `access_key`, private upload URLs or CDN metadata. The selected prefix is scoped to one plan/target and exact frozen ordered assets. Later edits explicitly preserve observed attachments: VK wall.edit may clear attachments when omitted. No additional `photos.getById` permission or byte-proof step is required.

Earlier native lifecycle checks demonstrated VK copy remapping and the need to retain attachments on wall.edit. Their historical SHA/CDN proofs do **not** remain a requirement for new publications. Live acceptance and ordinary native authorization, CAS and no-duplicate guards remain separate.
