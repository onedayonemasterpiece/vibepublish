# VK photo upload recovery

Status: Not confirmed by user. The reported HTTP 504 media-upload incident is Not done until the authorized same-post edit is verified live.

Fixed requirements:
- Keep approved immutable assets and native post identity unchanged.
- RGB single-frame PNG/WebP photos may use a metadata-free, same-dimension JPEG92 (4:4:4) wire derivative only when smaller. No resizing, visual generation, alpha flattening or asset replacement.
- Retry only the photo staging upload for explicit HTTP502/503/504 or the existing valid empty-photo receipt. Use at most three total attempts with a fresh upload server/form and one/two-second delays.
- No added retry of photos.saveWallPhoto, wall.post or wall.edit, API errors, timeouts or uncertain effects. Existing CAS, intent freezing and explicit recovery admission remain.
- Log existing bounded HTTP/phase/timing diagnostics without bodies or private URLs.

The observed incident returned HTTP504 in approximately4.4 seconds; the client deadline is25 seconds. Increasing that deadline is not a fix for an explicit upstream response. Four approved PNGs measured9,002,185 bytes and in-memory JPEG92 derivatives2,143,621 bytes, with unchanged dimensions. Size reduction is measured; elimination of upstream failures is not guaranteed.

Regressions cover smaller-only encoding, dimensions, source immutability, metadata exclusion, alpha preservation, multipart MIME, fresh-server retry budget, nonretryable statuses and no repeated photo save or public mutation.
