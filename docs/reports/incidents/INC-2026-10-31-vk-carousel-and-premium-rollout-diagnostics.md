# INC-2026-10-31 — VK carousel handoff and Telegram Premium rollout diagnostics

Status: `Open`  
Product acceptance: `Not done` for the requested VK edit and full-caption Telegram scheduling.  
Evidence cutoff: **2026-10-31 07:27 UTC**. All times below are UTC unless explicitly stated.

## Summary and scope

The owner requested a factual diagnostic handoff for their own coding agent, not another publication attempt. This document records the observed failures, exact receipts, unknowns and minimal verification work. It does **not** deploy a fix, change a post, restart an executor, or grant additional access.

Evidence labels:

- **Observed:** connector/runtime result reported by the executor that made the call; exact identifiers retained for authorized reconciliation.
- **Repository-verified:** documentation/metadata read directly while preparing this document.
- **Hypothesis:** plausible explanation requiring code/runtime inspection.
- **Unknown:** not established by the available evidence.

This is a consolidated incident handoff, not an independent replay of every provider call. The GitHub repository is public. No tokens, credentials, signed download URLs, private message links, private conversation text or host paths are included. Operational IDs are locators, not authorization.

| Work item | Established state | Not established |
|---|---|---|
| Aqueduct colorized image + CTA | Generated, visually checked, imported as a verified VibePublish asset | VK edit has **not been sent** |
| Existing VK original photo | Public post exists; authorized preview available | Transferable full original / reusable native attachment reference not exposed by the inspected Vibe read surface |
| VK media edit | Not attempted | Whether the deployed API supports the requested safe two-photo edit |
| Telegram Premium fix | PRs #113/#114 merged, reported green CI | Running API/worker had not advanced to merged release at latest runtime check |
| Two requested scheduled VK posts | Provider schedules verified | Must not be scheduled again |
| Corresponding Telegram posts | Not found in checked queues; full-caption preview blocked | No successful Telegram scheduling receipt |
| Existing rollout executor | Still working/unconfirmed, generating at last exact read | No terminal deployment outcome; no duplicate executor authorized by an unknown outcome |

**There is no uncertain VK mutation in the carousel case.** The delay was a long asset upload followed by an unresolved original-media/reference capability question. Calling all of this “being checked” obscured the real stage.

## Impact

1. Requested update of existing VK post was not delivered.
2. Caption-limit correction existed in GitHub but was absent from observed active processes; Telegram counterparts remained unscheduled.
3. User could not tell whether a write was pending, blocked, never issued, or completed.
4. A multi-target historical publication (Telegram + VK) makes an unscoped edit unsafe: this task is VK-only.

## A. Existing VK post: exact requested outcome

Target: **https://vk.com/wall-241261191_223**, main destination `lovekenig_vk`, owner `-241261191`, post `223` — **not** the announcements destination.

Original published time: **2026-10-30 19:00 UTC** (21:00 Kaliningrad).

Public content identifies Ulitsa Dmitriya Donskogo / the aqueduct, Kaliningrad, 1955–1960; author unknown; source archive of Evgeny Viktorovich Akhmatov.

Requested final state:

1. Same existing post ID and publication, not delete/repost.
2. Photo 1: generated colorization with three attribution lines and **“Оригинал →”** CTA.
3. Photo 2: the existing original photo, not a substituted low-resolution preview.
4. Preserve existing post text and add: **“Если вы заметили неточность в колоризации, пожалуйста, напишите в комментариях”.**
5. No Telegram edit, unrelated destination change or new schedule.

### Image provenance and quality boundary

Initial colorization used an authorized **549×768 JPEG preview, 62,850 bytes**, not a retrieved full-resolution original. Colors are plausible restoration, not documentary verification; generated small details must not be described as historically exact.

CTA PNG source:
- Bytes: **2,554,076**
- SHA-256: `75cd3f864cdf6c8bc34f8a683e3767245e99caee6d9c8d5703d93f9dfac979ab`
- Final Vibe asset: `asset_6c90769aa4dc423c91bdbb4dcf4ce42f`
- Verified finish operation: `op_222df4b02ee4461cab0c1e439092e69a`

The asset ID refers to the sanitized ingress asset; original source-byte SHA is not a claim that VK will serve identical bytes after provider processing.

### Observed timeline

| Time, 2026-10-31 | Action and exact result |
|---|---|
| 06:56 | Vibe feed operation `op_1e348e83552d42d29f2f4894415b23c3` returned latest item `item_8618165a17a44dc18f27902594b734f0`; native postponed origin 94 became published post 223. |
| 06:58–07:00 | Initial colorization generated from the preview. |
| 07:15 | CTA + two-photo existing-post edit requested. |
| 07:16:42 | CTA generation finished; visual check confirmed CTA and attribution lines. |
| 07:16:55 | Vibe item read with the exact VK URL returned `item_link_provider_not_enabled`, `next_action=fix_input`, `retry_safe=false`. This is an input/provider-link route failure, **not** an access denial. |
| 07:17:04 | Read by previously returned exact item reference succeeded, operation `op_2a8b7342c0864f6c95926b945f9ccbff`. |
| 07:17:04.973 | Verified read returned `item_6e769077f6864935b3494722ef054cb6`, same owner/post, unchanged text; HTTP 200 from `wall.getById`. |
| Before 07:18:49 | Attachment import with a real client file ID but no `file.download_url` failed connector validation: `INVALID_ARGUMENT`, missing `file.download_url`. No operation created; no fabricated URL used. |
| 07:18:49.157 | Documented workspace upload began: verified `op_b49757d3dd024f40906b0aa0e570d972`, upload `upload_f6e470f515c24061bde16730ba6bd11b`, expiry 08:18:49.154. |
| 07:18:49–07:25:56 | Thirteen sequential chunks accepted; approximately 30 seconds per connector call by elapsed observation, not a measured server latency. |
| 07:25:56.369 | Import finish verified: `op_222df4b02ee4461cab0c1e439092e69a`, received 2,554,076 bytes, state completed, asset above. Total upload interval about **7 min 7 sec**. This is upload, not generation or publication. |
| 07:26:02.770 | History read `op_312ff7c20baf4f24b794fe8ba3516594` verified, returned historical tracked publication and an item with `media_projection_not_enabled`. |
| 07:26:20 | Publication status read returned historical completed operation/revision, but no original asset reference. |
| Cutoff | **No media-edit or text-edit was called.** Work stopped when the owner requested this diagnostic handoff. |

Workspace upload used the documented maximum **196,608 decoded bytes/chunk**; final chunk 194,780 bytes. Offsets:
`0, 196608, 393216, 589824, 786432, 983040, 1179648, 1376256, 1572864, 1769472, 1966080, 2162688, 2359296`.

Stable keys:
- begin: `vk223-cta-bytes-begin-20261031`
- chunks: `vk223-cta-bytes-chunk-{offset}-20261031`
- finish: `vk223-cta-bytes-finish-20261031`

Do not create new uploads merely to retry this already verified asset.

### The actual unresolved gap

History result:
```text
media_projection_not_enabled
This checkpoint returns text and timing; provider media downloads are not exposed
```

Tracked publication: `pub_79ad449f63294f389592ee945b67a9ca`, revision **1**. Its status returned historical operation `op_3442b98040ff44e0b5104cf78b561ae8`, state scheduled / operation_complete true, and **both Telegram and VK deliveries**. This historical status is not an edit receipt and is not evidence that the public post is currently unpublished.

Authorized EventsBot resolved the original as an opaque photo asset and exposed its preview. That did not provide a transferable full-resolution Vibe asset or supported native reuse input. No private download URLs, browser credentials or CDN bypass were attempted.

**Unknown:** can deployed Vibe media-edit preserve/reuse the observed existing attachment while prepending a new asset? It was not tested because there was no safe complete two-photo input. Do **not** translate the projection error into “VK wall.edit unsupported.”

Repository-verified [VK media binding contract](../../features/social-operations/vk-media-binding.md) explicitly says later edits preserve observed attachments because VK wall.edit can clear them if omitted. It forbids requiring CDN byte proofs / additional photos.getById permissions. This suggests inspecting the existing adapter and stored bindings first, not building a download-and-fingerprint subsystem.

Repository-verified [asset ingress](../../operations/asset-ingress.md) documents both workspace chunk ingress and authenticated HTTP ingress. The observed chunk route is supported behavior. Whether its latency originates in connector delivery, server handling or client sequencing is **unknown**.

## B. Telegram Premium: source delivery is not deployment

Related incident locator: `inc_098d0954bca16cd4b7ed8a1f`.

### Reported GitHub delivery

- [PR #114](https://github.com/onedayonemasterpiece/vibepublish/pull/114), baseline/MAX correction: merged **2026-10-30 16:49:44**, merge `b79616e4d186706db165fa05091a836bea5c02cc`, reported CI run 525 successful.
- [PR #113](https://github.com/onedayonemasterpiece/vibepublish/pull/113), Premium caption behavior: merged **2026-10-30 17:05:46**, merge `1052fb3f9622e1f540db4f917ff4001ab9644794`; PR head `755999bf1aa74e12ab04eb4cd8d855bc40494520`, reported CI run 526 successful.

Intended behavior to inspect in source: actual Telethon user-account/Premium capability is checked; Premium may use 4096 caption limit, bot/non-Premium remains 1024, unknown account capability fails before upload. Do not simply increase a constant for every sender.

### Runtime evidence

Observed active **API and worker** release:
`c1053811c2c46c2e56633b8b4fec040f03cfdb78`.

| Runtime observation | Result |
|---|---|
| Oct 30 18:07 | Old release active; process start Oct 29 20:39. |
| Oct 31 05:40:59 | Old release active; process restart Oct 30 20:20:24. |
| Oct 31 07:11:41 | Old release active; process restart Oct 31 06:29:22. |

Working checkout was reported clean/main at `1052fb3`; that is **not** process activation. No verified rollout receipt, actual Premium preflight or successful new full-caption Telegram preview was available at cutoff.

Existing lineage check to inspect/reuse:
`python3 deploy/devcoveer/check_release_lineage.py --candidate <merged SHA>`.

### Existing executor must be reconciled, not duplicated

Existing rollout job: `80c886a5-69bb-4c17-98d0-535d495f9851`; request key `vibepublish-premium-ci-rollout-approved-20261030`.
- STARTED Oct 30 16:25:41.
- Last reported progress Oct 30 16:50:05; unconfirmed.
- Earlier job `5ef3f4e0-4e46-454f-bfef-9a5220cc216f` was BLOCKED at 16:20.
- A continuation was blocked at the assistant approval layer on Oct 30 18:08; that is not a VibePublish API error.
- Owner renewed authorization Oct 31 07:10.
- Same-executor continuation at 07:12, request `vibepublish-limit-rollout-owner-20261031-0710`, returned `INVALID_ARGUMENT`:
  `The agent or delivery outcome in this chat is still working/unconfirmed (job 80c886a5-69bb-4c17-98d0-535d495f9851, unconfirmed). Reconcile before continuing; never launch a duplicate.`
- **No continuation prompt was sent.**
- Read-only reconciliation job `647ebe4a-3d95-4eb3-a2f4-227f4dcaa46e`, queued 07:13:26; exact observation **07:14:56**: `answering=true`, `reply_generating=true`, visible Stop button, `inaccessible_frames=1`, `reply_text=null`.

Unknown executor completion is different from unknown provider publication. Do not stop/restart or launch another writer merely to bypass this guard. Reconcile the original executor and actual process releases first.

## C. Scheduled work: preserve existing VK effects

Full supplied texts, footer and original media must remain intact; shortening was not the requested solution.

### “Тигр в комнате”

Requested time: **2026-11-01 08:30 UTC / 10:30 Kaliningrad**, announcements destinations.
- Text 1258 characters; with footer 1293.
- Original image SHA: `abaedb2033c97afe336dc3a24c3a515ea1260c4b4e69b7ec9313f643dbc4498b`.
- Asset: `asset_d58a54d19fef479f92760ba812a5bb74`.
- VK publication: `pub_e8ff69837c7542f89df03f6139a68099`.
- VK operation: `op_0891374570ff4b2185eddab31d7e18f2`.
- Verified readback: `op_68df4a75817e4057ae0a3c866b20f0f4`.
- Original native item: `item_1098194d2c4a4652b7dcf6a2ff748b93`.
- Recent native queue item: `item_31b2771073b2402ea7afdc7696db383f`, confirmed requested time.
- Telegram full queue read 05:36 contained three other posts and no Tiger.
- Telegram preview rejected `network_footer_limit`; no successful TG schedule receipt.

### Sculptures / Svetlogorsk

Requested time: **2026-10-31 08:30 UTC / 10:30 Kaliningrad**, main destinations; complete text + **six cards**.
- VK publication `pub_d021403dec4a4d1ca13f165f6ee5888b`, revision 2, provider_scheduled.
- VK operation `op_a88fc7216315404c8c5b0dddb47d57dd`.
- Verified readback `op_dcd75cd462de410197b8e6a1d4b6bb4d`.
- Recent queue item `item_5d2c2726a09c42609c698295698e33b8`.
- Telegram preview failed `network_footer_limit`; execute was not called.
- Telegram reads at 05:39 / 06:31 covered 58 items over two pages, no matching sculpture or requested slot: `op_f21a5c8c68c34095a511cb75bf89580b`, `op_2c410802ea474c3f9dd1158099f541c3`.
- Those pages are **not an atomic queue snapshot**; absence is bounded evidence, not perpetual proof.

**Do not repeat either VK schedule.** Before any later Telegram retry, reread the intended destination/native queue and reconcile exact operations. This handoff itself performs no scheduling. If the target time has passed, do not silently substitute “publish now.”

## Root Cause: established versus candidate

| Finding | Classification |
|---|---|
| Old release in active API + worker | Established deployment gap at observed times; reason rollout did not finish remains to inspect |
| Caption preview rejects >1024 on old runtime | Observed; consistent with absent Premium correction, not independent proof all new code is correct |
| Missing `file.download_url` | Connector input-contract failure, before asset operation |
| Long 13-chunk ingress | Observed successful upload with poor latency; bottleneck unlocalized |
| URL read fails but item-ref read works | Capability/input routing mismatch; no permission denial |
| `media_projection_not_enabled` | Observed read-surface limitation, not proof media edit unsupported |
| Original full-photo reuse unavailable to executor | Operational blocker; inspect persisted/native attachment bindings and adapter contract |
| Publication status historical and multi-target | Wrong evidence surface for current VK-only media edit |
| Existing executor generating / unconfirmed | Launcher coordination state; do not equate with pending VK write |
| Assistant approval routing / “checking” language | Orchestration and communication failures, not Vibe provider defects |

### Separate assistant failures

Delivery approvals were at times routed against unrelated task context; one authorization application failed after authorization changed. This prevented assistant actions before service mutation. These incidents should be investigated in the assistant delivery/approval layer, not attributed to VK or VibePublish.

The assistant's status language did not distinguish upload, capability inspection, approval block and unissued edit. A useful report should name **stage + exact effect + blocker**: e.g. “asset imported; VK post unchanged; original attachment reuse not exposed.” No hidden-policy details or private approval payloads are needed to diagnose that communication failure.

## Fix / minimal code inspection requested

No fix is made by this document. Start with existing code and canonical contracts:

- `contracts/social_mcp_v1.py`
- `social_operations/service.py`, `storage.py`, `worker.py`, `server.py`, `assets.py`
- `adapters/vk.py`, `adapters/vk_transport.py`, `adapters/telegram.py`
- `deploy/devcoveer/`
- [MCP contract](../../features/social-operations/mcp-contract-v1.md)
- [VK media binding](../../features/social-operations/vk-media-binding.md)
- [Asset ingress](../../operations/asset-ingress.md)

Questions, in priority order:

1. What is the existing **target-scoped edit** path for a published native VK item? Does it preserve exact observed original attachments and accept an inserted asset? Can it do this without downloading an original again?
2. Where are ordered native attachment IDs/frozen asset bindings stored, and why are they not usable from the inspected read/status surfaces? Is the gap schema exposure, routing, missing stored provenance or adapter implementation?
3. Why does exact URL read reject while an item_ref reaches wall.getById? Is this an intentionally unsupported input or stale capability advertisement? Return a precise, usable alternative early.
4. Can required edit capability/original-reference availability be established **before** a multi-minute upload? Do not add new review queues or fingerprint gates contrary to the existing binding contract.
5. Where do the roughly 30-second chunk calls spend time? Measure client/connector/server boundaries. Retain chunk limits and request identities; do not remove authentication or fabricate download URLs for speed.
6. Why did active API and worker remain `c1053811` after merge? Inspect release lineage, activation evidence and original executor outcome. Checkout HEAD is not adequate deployment evidence.
7. Does deployed Telegram validation use actual sender capability **before** rejecting the full caption or uploading media? Test bot, non-Premium, Premium and unknown account paths.
8. Do status/preview results clearly distinguish unissued, input-rejected, accepted, provider-pending, verified, and historical state?

Prefer the smallest correction of an observed contract gap. Do not introduce a new scheduler, general queue, duplicate executor, broad permission, uncontrolled retry, arbitrary timeout increase or blanket caption-limit increase.

## Regression Checks and live acceptance

### VK carousel

- Same exact owner/post `-241261191/223`.
- Exactly two photos in required order: frozen CTA colorization, unchanged original attachment.
- Preserve existing text and add only requested paragraph.
- No Telegram or other delivery changed, even if historical publication includes them.
- Read back exact target, post ID, text and ordered attachment IDs through ordinary authorized provider path.
- Respect VK copy remapping; do not require final CDN bytes to equal source hashes.
- Missing original reference fails before mutation with an actionable error, rather than dropping an attachment.
- Uncertain write response reconciles original operation/request key before retry; no duplicate/repost.
- A successful upload receipt alone cannot satisfy post-edit acceptance.

### Telegram / release

- Verify exact merged candidate lineage and actual API **and** worker release after any authorized rollout; health and ordinary operation readback.
- Exact full caption/footer and all required images retained.
- Premium user succeeds within supported real provider limit; bot/non-Premium limits retained; unknown capability fails before side effects.
- Existing VK schedules remain one each.
- Exact Telegram native queue confirms correct destination, full text, all media and requested time after an authorized schedule.
- Do not treat a split multi-page queue read as an atomic absence guarantee.
- Reconcile original launcher job and operation receipts before continuing; no second writer.
- Source/CI, deploy, provider receipt and user acceptance are separate states.

### Security and privacy

- Preserve tenant/principal isolation, OAuth/scope checks, immutable revisions, CAS and idempotency.
- No access_key, signed URLs, session files or private message content in logs/docs.
- No CDN/private-path/credential workaround and no weakened tests to obtain green status.

## Release Evidence and Follow-Ups

At this snapshot, only the CTA asset import and existing VK schedules have verified service/provider receipts described above. The requested carousel is **not changed**, Premium deployment is **not verified**, and corresponding Telegram schedules are **not established**.

Next useful handoff result is a short source-backed root-cause statement, minimal patch if warranted, exact tests and deployment/provider acceptance evidence. The owner will launch their code agent; this document does not start another executor.

Public-safe diagnostic only; no source/runtime changes were made while writing it.
