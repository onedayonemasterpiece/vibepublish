# VK photo upload recovery

Status: Not confirmed by user. The reported HTTP 504 media-upload incident is Not done until the authorized same-post edit is verified live.

Fixed requirements:
- Keep approved immutable assets and native post identity unchanged.
- RGB single-frame PNG/WebP photos may use a metadata-free, same-dimension JPEG92 (4:4:4) wire derivative only when smaller. No resizing, visual generation, alpha flattening or asset replacement.
- Retry only the photo staging upload for explicit HTTP5xx (including 500), 429, timeout/network failure, vk_upload_transient_empty_photo, vk_upload_response_invalid. Use at most five total attempts with a fresh upload server/form and 1/2/3/4-second delays. 403 and SSRF/invalid URL are NOT retried.
- No added retry of photos.saveWallPhoto, wall.post or wall.edit, API errors, timeouts or uncertain effects. Existing CAS, intent freezing and explicit recovery admission remain.
- Log existing bounded HTTP/phase/timing diagnostics without bodies or private URLs.

After a terminal HTTP upload failure whose explicit retry key was already consumed, do not mint another retry key. Use the existing owner-only reconcile with a fresh same-post item ref to create a local baseline revision, then submit a separate explicit edit. The old terminal receipt remains immutable; no provider effect occurs during baseline refresh. Unknown/dispatched attempts remain ineligible.

The observed incident returned HTTP504 in approximately 4.4 seconds; the client deadline is 25 seconds. Increasing that deadline is not a fix for an explicit upstream response. Four approved PNGs measured 9,002,185 bytes and in-memory JPEG92 derivatives 2,143,621 bytes, with unchanged dimensions. Size reduction is measured; elimination of upstream failures is not guaranteed.

Regressions cover smaller-only encoding, dimensions, source immutability, metadata exclusion, alpha preservation, multipart MIME, fresh-server retry budget, nonretryable statuses and no repeated photo save or public mutation.

## §18.1 / W2 policy update (2026-10-27)

**Retry attempts increased to 5** (was 3). Each attempt gets a fresh `getWallUploadServer` call.

**HTTP 429 added to transient retry conditions** (was only 502/503/504). Now retries on: 5xx (including 500), 429, timeout/network failure, vk_upload_transient_empty_photo, vk_upload_response_invalid, vk_transport_failed.

**403 and SSRF/invalid URL remain non-retryable.**

**Backoff:** 1s, 2s, 3s, 4s (was 1s, 2s).

**JPEG92 wire derivative semantics unchanged** (vk_photo_wire.py not modified).