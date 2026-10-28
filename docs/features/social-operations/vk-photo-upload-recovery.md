# VK photo upload retry

Status: **Fixed** policy D4 / §18.1; reported upstream failures remain **Not done** until live acceptance.

Native VK photo upload uses immutable source assets. RGB single-frame PNG/WebP may use the existing metadata-free same-dimension JPEG92 (4:4:4) wire derivative **only when smaller**; it does not replace the source, resize or flatten alpha.

On a **transient media-upload** error, retry up to **five total attempts**. Obtain a new `photos.getWallUploadServer` on every attempt, with backoff of 1, 2, 3 and 4 seconds. Transient classes: HTTP 5xx including 500, HTTP 429, network/timeout, empty photo (`vk_upload_transient_empty_photo`), `vk_upload_response_invalid`, `vk_upload_failed` and `vk_transport_failed`. HTTP 403, rejected URL/SSRF validation, permanent input/permission errors and `photos.saveWallPhoto` failures are **not** retried by this photo-upload loop.

After each successful save, write `vk_photo_staging` with the saved native ID, including for scheduled posts. On restart, reuse saved prefix IDs without access keys; upload only assets not yet successfully checkpointed. The same-guid `wall.post` recovery is separate from upload retry and does not allow a second independent publication intent.

Original observed 504 incident: upstream returned after about 4.4 s under a 25 s client timeout. Increasing HTTP timeout would not fix that explicit response. No live provider calls, token changes or deployment are part of W2.
