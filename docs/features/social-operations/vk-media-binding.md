# VK photo identity rebinding

Status: **Not done** (reported defect); owner requirement to support native VK
postponed posts is **Fixed**. Engineering proof policy is **Not confirmed by user**.

The existing design requires provider binding and ordered media verification
(`implementation-design-v1.md`, Native execution/readback and Fingerprints).
It does not require saved-photo IDs to survive VK copying a user upload to a
community wall. Observed live VK evidence already shows that remapping.

Implement a narrow adapter proof, not a weaker count/text-only acceptance:

1. For a user-owned saved wall photo destined for the authorized community,
   fetch a bounded decoded provider image before wall.post/wall.edit. Persist
   saved ID, SHA256 of its exact provider bytes, MIME, byte count and dimensions
   in the existing durable pre-effect checkpoint; never persist CDN URLs/keys.
2. On exact target/post readback, identical ordered IDs retain the existing fast
   path. Changed IDs require a photo-by-photo proof in the same order: current
   photo owner must be the target community; provider rendition dimensions and
   exact bytes fingerprint must match that position's pre-effect evidence.
3. Record the old-to-current ID binding in a response checkpoint. Source SHA256
   remains the source identity, not a claimed hash of provider-transcoded bytes.
4. Edits/reschedules reuse the verified current IDs. Crash recovery reads the
   same checkpoint and remote object; it never repeats upload or wall.post.
5. Missing evidence, changed bytes/order/count, incomplete/forbidden reads or
   unstable post identity stay unresolved. Old checkpoints cannot invent proof.

Transport: HTTPS VK CDN allowlist, pinned public DNS, no redirects/proxy/cookies,
no auth headers, 10-second total including DNS, 20MiB maximum per image, valid
single-frame image with bounded decoded dimensions. Image URLs are untrusted API
metadata and are not accepted as arbitrary client download endpoints.

Reference: official VKCOM/vk-api-schema `photos/methods.json` (saveWallPhoto,
getWallUploadServer) and `photos/objects.json` (photo identity and sizes). The
observed additional orig_photo field is optional, not an assumed schema guarantee.
Real before/after fingerprints and lifecycle receipts are required for acceptance.
