# VK allocation-only recovery

Status: Not confirmed by user. Implementation and offline verification do not constitute live acceptance.

The existing explicit `publication_update` reconcile command can recognize one bounded outcome: an immediate VK wall publish with one MP4 allocated a native video, then synchronously rejected its upload URL before upload and wall submission. It does not call the provider, publish, upload, delete the allocated video, or retry the original intent.

Admission requires the original dispatched unknown attempt, intact plan/checkpoint and actor/binding/connection authority, a `vk_video_allocated` checkpoint with one exact target-owned video and no wall ID, and correlated durable diagnostics ending in completed `video.save` followed by failed `execute` with `vk_upload_url_invalid`. Absence of logs is never sufficient. The local validation ordering is part of this invariant: the URL is validated immediately after the allocation checkpoint and before media upload.

The original attempt becomes partial with `vk_video_allocation_only`, `retry_safe=false`, and historical `dispatched=1`. Its native allocation and original checkpoint remain preserved with a digest-bound proof. No wall item or published receipt is fabricated. The existing connection guard exempts only that validated proof; any other unknown attempt continues blocking. Stale authority or tampered proof fails closed. Repeating reconciliation cannot rearm a provider effect.

Upload interruptions, HTTP errors, unknown wall writes, scheduling, Stories, edits, multiple assets and missing/mismatched evidence are excluded. This change does not accept previously rejected upload hosts or repair video publishing.

After this observation-only resolution, an independent, never-dispatched carousel edit may use its existing one-time `retry_failed` command if eligible. The frozen intent and native CAS still apply. Verify the same public post, its caption and ordered media after completion.
