# INC-2026-10-27 — VK four-photo Börse carousel scheduling

Status: **Mitigated** (native scheduled post confirmed on 2026-10-27); upload/readback robustness **Not done**; owner acceptance **Not confirmed by user**.

## Summary

An owner-authorized four-card carousel about the historical Königsberg stock exchange (Börse), sourced from Robert Albinus, *Lexikon der Stadt Königsberg Pr. und Umgebung* (1988), pp. 42–43, was requested for the VK community `lovekenig_vk` at **2026-10-27 15:00 Europe/Kaliningrad (+02:00)**.

Initial execution failed twice (one immediate attempt plus one automatic continuation) **before any `wall.post` dispatch**. The first failure was an upload-server HTTP 500 for the second image. The second failure was `vk_photo_read_failed` during verification of a just-saved provider rendition. One later **explicit, policy-guarded `publication_update.retry_failed`** on the *same publication, revision and attempt* completed. VibePublish observed `provider_scheduled`, checked ordered media binding, and a separate native `read(item)` confirmed the text and 13:00 UTC scheduled time.

There is **no proven product code fix** yet. Do not classify a successful manual retry as a permanent resolution of the underlying defects.

## Impact

- The four-page publication was missing from the VK native queue after the initial command; the assistant originally reported failure.
- The owner had to challenge the incomplete handling before a safe explicit retry was attempted.
- The original scheduled time was preserved; no immediate-send fallback or separate duplicate publication was used.
- VK may have allocated extra private saved photos in pre-post stages. This incident does not assert that those private allocations were absent or deduplicated.

## Evidence and timeline

Times are **UTC** on 2026-10-27; add 2 hours for Kaliningrad.

| Time | Evidence |
| --- | --- |
| 07:53:48 | VibePublish accepted one native scheduled publish operation; four immutable asset references. |
| 07:53:57 | First photo successfully reached `photos.saveWallPhoto`. Earlier media-upload HTTP 200 attempts were followed by new upload-server requests. |
| 07:54:00 | Image 2 upload to `pu.vk.com`: **HTTP 500**, code `vk_http_failed`, phase `media_upload`, elapsed **947 ms**, no `wall.post` dispatch. |
| 07:54:00–07:54:02 | VibePublish automatically resumed the same business operation (one server continuation). Staging restarted from image 1/4. |
| 07:54:33 | Image 2 reached successful `photos.saveWallPhoto` on continuation, after repeated HTTP 200 uploads. |
| 07:54:37 | `execute` failed with `vk_photo_read_failed` about 3.9 seconds after `photos.saveWallPhoto`; terminal state `blocked`, `dispatched=false`. |
| 08:11:~ | The agent invoked **one** explicit `retry_failed` with a stable recovery key, scoped only to `lovekenig_vk`. Server admitted the frozen original revision. |
| 08:12:46 | On explicit recovery, the four-photo staging completed; `wall.post` was invoked and completed. |
| 08:12:48–08:13:01 | The provider-owned scheduled item was read back: `state=scheduled`, `observed=provider_scheduled`, `media_check=provider_binding`, `requested_at=effective_at=2026-10-27T13:00:00Z`. |
| 08:13:39 | Separate `vibepublish_read(kind=item)` returned the target community post's full editorial text and `scheduled_at=2026-10-27T13:00:00Z` from the provider. |

Private operation reference: `op_f4a39355e11044809162ee3d0b7dd1c6`; publication reference: `pub_11580c9445c544fdb06c5322eac2269e`. These are evidence locators, not public post URLs or access grants. Do not include signed media URLs, tokens, raw VK upload bodies, or private connection data.

### Actual media size (not presumed original PNG transfer)

All four source cards were **1080 × 1350 PNG**. Transport emitted same-dimension `image/jpeg` derivatives:

| Ordinal | Stored source PNG bytes | Observed VK JPEG payload bytes |
| ---: | ---: | ---: |
| 1 | 1,735,293 | 256,539 |
| 2 | 2,263,412 | 378,429 |
| 3 | 1,656,875 | 339,776 |
| 4 | 2,205,530 | 372,291 |
| **Total (one each)** | **7,861,110** | **1,347,035** |

The successful manual recovery used these same original assets, dimensions and order. Repeated upload attempts occurred for images 3 and 4, but **all four were ultimately accepted by VK**. Large PNG source size is therefore **not an established cause**. The wire sizes (0.26–0.38 MB/image) argue against a hard VK file-size rejection. The earlier HTTP 500 remains a real upstream response, not a local size-validation error.

## Root-cause analysis: proven versus unknown

**Confirmed failure mechanisms**

1. `adapters/vk.py::_stage_images` retries `vk_upload_transient_empty_photo` and media-upload HTTP **502/503/504**, each with a fresh upload-server allocation, up to three tries. Explicit **500** is not in that local retry allowlist. The HTTP 500 therefore reached the operation level, which performed one automatic continuation.
2. After `photos.saveWallPhoto`, `_stage_images` immediately calls `_photo_proof` for user-owned saved photos, which calls `adapters/vk_transport.py::image_fingerprint` to download an authorized VK CDN rendition and validate its fingerprint before public posting. This read-only check failed in the automatic continuation.
3. `image_fingerprint` currently reports the **same** `vk_photo_read_failed` code for non-200 GET, unexpected content type or encoding, and various transport/timeout/decode exceptions; it does not emit the structured phase/status/cause evidence needed to distinguish them. The specific response/failure class for this incident is **unproven**.
4. Staging restarted at **image 1/4** after the initial failure and again on explicit recovery, notwithstanding a previous successful image-1 save. The existing `vk_photo_staging` and `staged_photos` mechanism needs investigation for retention and reattachment of verified prefixes in this exact path. No claim that a checkpoint was durably present is made without a read of its underlying state.
5. The first failures are **pre-`wall.post`** (`dispatched=false`). By design, the generic receipt's `retry_safe=false` is not permission for arbitrary new `publish` calls. The separately authorized `publication_update.retry_failed` has a strict zero-dispatch admission guard; that guard **did admit this one safe recovery**.

**Not established**

- The concrete VK CDN GET status, MIME, redirect, timeout, DNS or decode cause for `vk_photo_read_failed`.
- Whether the failed attempts left provider-private photo allocations or why particular HTTP 200 upload responses caused additional staging attempts (behavior is compatible with empty-photo receipts).
- Exact source revision actually loaded in the deployed worker. GitHub code paths explain observed behavior but deployment provenance requires separate verification.

## Proposed fix (none implemented in this documentation PR)

### P0 — Harden and diagnose VK CDN fingerprint reads

- In `image_fingerprint`, emit sanitized, bounded **read-only** diagnostics: `stage=photo_rendition_read`, allowed URL host category (never URL/query/token), numeric HTTP status, coarse content-type/encoding category, elapsed time, and static failure reason (`http_status`, `wrong_mime`, `unexpected_encoding`, `timeout`, `connection_failure`, `decode_invalid`, `size_limit`). No signed URLs, response bodies, cookies or credentials.
- Retry **only safe read-only rendition GETs** on demonstrably transient errors with a short finite budget and preserved original photo ID/fingerprint. No repeated `photos.saveWallPhoto` or `wall.post` as a side effect of a failed CDN GET.
- Keep exact byte/dimension/owner/order identity checks and fail closed on mismatches, forbidden URLs, redirects or ambiguous provider data.

### P1 — Staging recovery and transport classification

- Inspect how verified `vk_photo_staging` prefixes are checkpointed and restored through ordinary automatic continuation and explicit `retry_failed`. Prefer resuming a proven prefix instead of re-uploading image 1; never infer success from an unverified save or transient upload receipt.
- Determine whether HTTP **500** from `pu.vk.com` qualifies for a narrowly scoped pre-`photos.saveWallPhoto` retry. **Do not** blindly extend the allowlist: first prove that a new upload-server allocation cannot duplicate a public effect, with immutable original media and bounded attempts.
- Surface progress in user-facing receipt as `uploading image 3/4`, `verifying provider image`, `pre-wall safe retry available`, or `public effect uncertain`; avoid one opaque `vk_photo_read_failed` with `fix_input` when no input defect was observed.

### Agent recovery playbook

- On a terminal `blocked` status, check the exact attempt's `dispatched/observed` evidence and the native scheduled queue before suggesting resubmission.
- If there is **proved zero wall dispatch** and the owner still authorizes delivery, attempt **one** explicit `retry_failed` with a durable key for the same original publication/revision/failed destinations; follow `status` and native readback. Never use a fresh `publish` request as a retry or bypass the backend admission guard.
- If any wall effect is uncertain or dispatched, **observe/reconcile only**; no re-post. A user-visible retry failure should state the precise code and the absence or uncertainty of a native queue item.

## Regression and acceptance

1. Inject upload HTTP 500, 502, 503, 504, a successful HTTP 200 with empty `photo`, and genuine `photos.saveWallPhoto` success. Assert exact phase classifications and bounded retry behavior.
2. Inject transient image rendition GET 503→200, 403, redirect, wrong MIME, bad bytes and a 10-second timeout; prove sanitization, exact identity and absence of extra save/post side effects for GET retry.
3. Kill and resume between first-photo proof/checkpoint and second-photo upload; prove a saved verified prefix is reused **only** with durable evidence and exact identity, while an unproven prefix is not reused.
4. Simulate blocked zero-dispatch `publish` followed by exactly one `retry_failed`; assert the same publication/revision/attempt identity and a single resulting `wall.post`. Idempotent replays must be inert.
5. Native acceptance: one four-photo VK community queue item, original ordered images with `provider_binding`, intact caption and **15:00 Kaliningrad**, no duplicate scheduled items, full provider readback. Do not label automated fixtures as real acceptance.
6. Validate emitted provider diagnostics contain no signed URLs, keys, token values, raw API bodies or sensitive headers.

## Related code and prior fixes

- [`adapters/vk.py`](../../../../adapters/vk.py) — `_stage_images`, `_photo_proof`, checkpoint logic.
- [`adapters/vk_transport.py`](../../../../adapters/vk_transport.py) — upload transport and `image_fingerprint`.
- [`adapters/vk_photo_wire.py`](../../../../adapters/vk_photo_wire.py) — size-reducing JPEG derivative without changing immutable source assets.
- [`social_operations/recovery.py`](../../../../social_operations/recovery.py) — exact guarded `retry_failed` admission.
- Prior merged PRs: [#69](https://github.com/onedayonemasterpiece/vibepublish/pull/69) (sanitized HTTP failure phase), [#72](https://github.com/onedayonemasterpiece/vibepublish/pull/72) (JPEG wire derivative/502–504 retry), [#73](https://github.com/onedayonemasterpiece/vibepublish/pull/73) (multi-photo budget), [#75](https://github.com/onedayonemasterpiece/vibepublish/pull/75) and [#76](https://github.com/onedayonemasterpiece/vibepublish/pull/76) (photo staging), [#77](https://github.com/onedayonemasterpiece/vibepublish/pull/77) (upload observability).

## Release evidence and follow-ups

- Confirmed **live**: same frozen owner publication, explicit safe retry admitted, `wall.post` returned, `provider_scheduled` plus `media_check=provider_binding`, and independent live item read at the correct time.
- **Not done**: root-cause instrumentation for CDN image reads, safe GET retries, verified-prefix restart behavior and their tests.
- **Not performed**: code modification, host deployment, further synthetic social writes, schedule edit/cancel. Maintain the already-created native scheduled post unchanged.
