# Resume verified VK photo staging

Status: Not confirmed by user. Live acceptance remains required.

An immediate VK photo publish/edit can resume its own verified staging prefix during an already-authorized never-dispatched retry or worker restart. A separately authorized tracked edit may reuse that prefix or a complete checkpoint from an earlier terminal, never-dispatched edit of the same publication and native post. The original terminal receipt and consumed recovery key stay unchanged. Explicit fresh-read baseline reconciliation and the separate new edit remain the admission workflow; reconcile itself never performs a provider write.

The worker selects only intact previous attempt/plan checkpoints with identical ordered immutable assets (the newly authorized caption may change independently), matching principal/actor/binding/connection authority and earlier revision, and an ordered verified prefix of native photos. Unknown/dispatched source attempts, other publications/posts, changed assets and stale authority cannot qualify. A matching but corrupt/incomplete proof fails closed instead of silently triggering a full re-upload; genuinely new assets use the ordinary upload path. No cross-publication media cache or guessed album matching is introduced. The same attempt is preferred before earlier revisions. After each successful save, `vk_photo_staging` records the verified prefix; later upload failures preserve it. Existing `vk_prepared` checkpoints require a complete set. Group-owned photos without fingerprints retain the previous ordinary path and are not reused by this mechanism.

The adapter validates and reuses the authoritative saveWallPhoto receipt IDs selected by the worker, following the same attachment path as fresh staging. It does not add photos.getById as a prerequisite or require additional reader permissions. Existing target readback/CAS and before-effect fencing remain mandatory. Actual post-edit readback verifies ordered media, including target ownership when VK reassigns photo IDs. A missing/deleted photo must fail the provider write or required readback; changed or unproven media cannot become verified. No access keys are fabricated, persisted or logged.

A complete verified prefix requires no getWallUploadServer, media upload or saveWallPhoto calls. A partial prefix's saved proofs are validated in full before uploading only the missing suffix. Saved photos are attached in the approved order; a fresh native CAS follows all staging. A later revision does not rearm the earlier retry key or erase previous failures.

Residual crash window: saveWallPhoto may succeed before checkpoint persistence. That newly allocated but unrecorded photo is not recovered by this change; this is not a claim of exactly-once media allocation or fully crash-safe preparation. Ambiguous public effects retain existing observation-only recovery and no-repeat guards. Consumed recovery keys never gain another send; further edits require the existing fresh-baseline/new-revision path.

The existing saveWallPhoto and wall.edit contract and final media-binding verification remain authoritative. This removes the added photos.getById precheck that returned provider error 200 in production; it does not change provider permissions. No upload host, credential, persistent permission, schema or dependency changes.

## §18.1 / W2 policy update (2026-10-27)

**Scheduled posts now supported.** The `not plan.get('scheduled_at')` check is removed; scheduled photo publishes/edits can resume verified prefixes.

**photo_proofs no longer required.** Checkpoints without `photo_proofs` are accepted. If present, structure is validated but not required. The `vk_staged_photos_invalid` error is only raised for structural violations.

**Negative owner_ids accepted.** Regex updated to `photo-?[1-9][0-9]*_[1-9][0-9]*` to accept community photo IDs (e.g., `photo-101_12345`).

**Checkpoint after each saveWallPhoto.** The `vk_photo_staging` checkpoint is written immediately after each successful save, including for 10-photo scheduled posts. No `scheduled_at` selector. No `access_key` persisted.