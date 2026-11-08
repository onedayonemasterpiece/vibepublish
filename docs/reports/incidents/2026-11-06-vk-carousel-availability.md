# VK carousel availability recurrence, 2026-11-06

Status: **Not done**. Investigation initiated; no software fix or live acceptance claimed.

## User-visible defect

The owner reports that photos **2 and 6** in the seven-photo Sovetsk carousel
https://vk.com/wall-241261191_244 are unavailable, and that individual photo
repairs have become a recurring practice. The requested outcome is a systemic
fix to publication, not another replacement of individual pictures.

Related open DevCoveer incident: `inc_b4ce8452c3997f4c35ffd141`
(VK Lake Tales photos unavailable in the owner mobile viewer).
Its 2026-11-02 evidence covered posts 231828790/2291, 2292 and
231920894/13092, 13093: all 40 CDN renditions returned HTTP 200 and decoded,
while the native viewer symptom remained unresolved. A prior in-place rebind
retained the same photo IDs and was explicitly **not** a repair.

## Evidence collected on 2026-11-06

- Exact VibePublish item read `op_49f22582ac06406496f8b932608d6443`
  completed `verified`. VK reported published post 244 and
  `postponed_id=240`, confirming the native scheduled-to-published transition.
- All seven image sources downloaded through the existing exact-read path.
  Reported image 2: JPEG, 1086 × 1448, 532492 bytes,
  SHA-256 `6b65dd640dc339b425ac96efd8e8ec924cb4e11c4fead8822e4657a1cd986d87`.
  Reported image 6: JPEG, 1086 × 1448, 512167 bytes,
  SHA-256 `fcd9a92111ea5551df505ecfe8e4c57cf8ca36e1ade4622369d7d5eb08c8b089`.
  These are downloaded-rendition facts, **not evidence of reader-visible
  availability**, and must not be used to contradict the owner's report.
- Live worker systemd read: active/running, working directory and script from
  release `ba57554964fce4c88fb59cee69223a486e1b166a`.
  Source checkout was clean at that same commit.
- Registered worker journal search for `241261191` over the preceding 48 hours
  completed with zero matches. This does not establish that publication was
  error-free: per-operation diagnostics may be stored outside the journal.
- Independent browser reproduction was attempted by the coordinating task but
  blocked by navigation timeout and then connection failure. It neither confirms
  nor disproves the reported viewer error.
- DevCoveer later stopped returning timely diagnostic responses. A read-only
  schema-discovery call was stopped; no repository/runtime mutation was submitted
  through that call. The registered `codex_home` read also failed with
  `file_type: registered host root must be a real directory`.
  Canonical incident/simplicity instructions were read from the repository.

## Source findings, not a proven root cause

At the observed release:

1. `adapters/vk.py:_stage_images` uploads each immutable source with a fresh
   wall upload server, calls `photos.saveWallPhoto`, and checkpoints the
   returned native ID immediately. Attachment strings contain owner and photo ID.
2. `_reuse_staged_images` restores saved IDs scoped to target, existing post
   and ordered source hashes; existing-post edits also check the exact baseline.
3. `_bind_copied_media` accepts ordered photo IDs from the exact wall post,
   including legitimate user-to-community ID remapping.
4. The canonical [media binding contract](../../features/social-operations/vk-media-binding.md)
   deliberately forbids CDN/fingerprint checks in publication and requires no
   extra `photos.getById` permission. The
   [staging contract](../../features/social-operations/vk-staged-photo-reuse.md)
   forbids persisting access keys and says to restage a saved photo if reuse
   requires a transient capability.

The adapter does not preserve an optional save-response access key in the
immediate attachment string. Whether that matters for these exact photos is
**unproved**. Working controls in the earlier incident also had an access-key/
community-album shape. Do not change credential handling or add access-key
persistence based on this hypothesis.

## Bounded systemic repair work

1. Recover the exact publication/edit event chain for postponed ID 240 and
   published ID 244, including the seven ordered staging IDs and final
   community IDs. Determine whether positions 2 and 6 differ from working
   positions in allocation, reuse, attachment representation or later edits.
   Retain only nonsecret correlation and shape metadata.
2. Observe the exact failed native/mobile viewer request and a working neighbor.
   Compare object availability and scheduled-to-published behavior, not just CDN
   byte retrieval. Use an existing authorized viewer/session; never extract or
   expose credentials. No new post or media replacement is authorized here.
3. Select the smallest normal-path change supported by the resulting evidence.
   Check existing mechanisms and all publish/edit/retry consumers. Preserve
   frozen asset ordering, prefix recovery, exact-post CAS, no duplicate public
   effects, native schedules, and the no-secret-checkpoint rule.
4. Add one distinguishing regression that fails on the observed broken path
   before the change and passes after it; extend existing provider/runtime tests.
   Document and test any affected reuse and native schedule transition.
5. Run required checks on the final commit, create/update the implementation PR,
   merge only under the owner's repository authorization, and separately verify
   deployment and reader-visible outcome. A green unit test, native receipt,
   merged PR, or CDN download alone cannot close this incident.

Do not add a repair queue, periodic reupload, blind retry, new publication,
CDN acceptance gate, or speculative photo-format conversion. Existing published
content remains unchanged. Any real external test publication or content edit
needs its own authorized target and purpose.

## Completion criteria

- A concrete causal difference between broken and working photos is evidenced.
- The normal publishing path handles that difference without manual photo repair.
- Regression and applicable repository checks pass on the exact delivered commit.
- Runtime release and actual VK viewer behavior are verified separately.
- The incident remains open until the reported user-visible behavior is resolved.

## Simplicity self-check

| Element | Observed need | Existing mechanism | Decision |
| --- | --- | --- | --- |
| One incident report | Repeated owner-visible failures without an established cause | Existing incident registry and docs | Reuse and connect evidence |
| Production code | Cause not yet established | Current VK adapter and native binding | No speculative change |
| CDN checks/reupload loops | Would not distinguish the known failure | Prior 40 successful downloads did not resolve it | Not added |

Net production-code lines: **0**. No runtime mutation, social publication,
credential change, or claimed remediation.

## 2026-11-08: post 259, intermittent CDN rendition availability

Status: **Not done; not fixed**. This adds a reproduced CDN symptom,
not a proven systemic root cause or native-viewer acceptance.

The [owner reported](https://mira-projects.slack.com/archives/C0CFP01K292/p1794129067781709)
that the last photo of published post -241261191_259 did not load.
The existing exact read had downloaded seven JPEGs; that did not test every
rendition used by a VK client. All provider probes below used the existing worker
release dfe3ec00076a6ca9055487cbfa39cfe22f38a8c3 adapter, production credential
resolver and current binding of read op_fc8e2dfff2fe4034acab5a92e411ad48.
No browser, credential change, provider write or post/media edit was performed.

### Saved observations

Times are UTC operation windows, not separately instrumented HTTP timestamps.

| Window | Durable receipt | Result |
| --- | --- | --- |
| 09:19:04.979–09:19:21.906 | op_fb5d474d6d7a888c434fca60 | First photo: 8/9 unique renditions decoded; size:r non-200. Last photo: all 9 decoded. Failed HTTP code not retained by the existing transport. |
| 09:24:47.534–09:24:53.533 | op_0789e11c8ca69afe496ed65b | One repeat of first/last size:r: first HTTP 200 and full JPEG decode; last non-200. |
| 09:38:08.493–09:38:14.924 | op_e86c28ac32f9176048ed7377 | First original/r: HTTP 200. Last original: HTTP 200; last r: HTTP 404, text/html, declared Content-Length 410. |
| 09:42:57.900–09:43:04.650 | op_13039c4b2553b3ae7c4a702a | Last original/r: HTTP 200 and full JPEG decode. Requested URL hashes match the preceding run; effective response URL hashes equal requested hashes for both. |

Last photo identity: photo-241261191_457239313; control first photo:
photo-241261191_457239307. Last original and r use sun9-51.userapi.com.
The original remained JPEG 1080x1350, declared length 519045,
SHA-256 dfad5897802ae1414b910393b58884602a5a45ec1b167641c5451c560dad94fc.
The recovered r was JPEG 540x675, declared length 215267,
SHA-256 47b61a60871b7867c2996da107064ecff0e9d6f7a91c0cd8dca9432f3b5c18b8.

The identical requested last-r URL hash across the 404 and 200 runs was
c96c6289c765cb352946483b48673200ba7fca497e468f78296d3e91a2ec7e32.
Last-original URL hash was
51bb5fcbd368fc29938de4e5e6bf9c9f236279e9a960250987d0c7a400dc08ac.
Only hashes/whitelisted metadata were retained, not URL values, queries,
access keys, auth headers or provider response bodies.

Scoped read-only SQLite receipt op_071dacd8d01726dfeb8a9df4 confirms:

- The original postponed 258 and published 259 have the same seven ordered
  community photo IDs, 457239307 through 457239313; no lost/reordered last ID.
- First/last source uploads were JPEG and each reached saveWallPhoto without
  its own retry. Upload HTTP 405 failures concerned photo 4; later execution
  resumed the saved prefix. Exactly one wall.post dispatch appears in this
  operation's 196 events.
- First save completed at 07:48:29.631204; last save at 07:50:43.891232;
  wall.post started at 07:50:43.917785 and completed at 07:50:44.815669.
  The subsequent exact read recorded legitimate VK photo-ID remapping.
- Raw save-response access-key presence and rendition URLs are not retained
  in the persisted plan/checkpoint/item projection. Zero persisted fields
  does not prove that provider responses lacked those fields.

### Causal limits and supported operations

The same requested rendition URL produced 404 then 200 without a change to
client request behavior or an application-issued provider mutation. The final
run also measured requested/effective URL equality. The failed run did not
record an effective URL hash. This is evidence against URL requoting as the
cause for this tested URL, not a claim about every provider URL.
[aiohttp documents automatic canonicalization](https://docs.aiohttp.org/en/stable/client_quickstart.html#passing-parameters-in-urls),
but no encoded=True change is justified by these observations.

The specific CDN/backend condition and relationship to the owner's exact
native-viewer request remain unknown. A later successful download is not a
repair or proof that the viewer defect is resolved. Upload corruption,
access-key loss and carousel mode have not been established as causes.

The reviewed [official VK photos API schema](https://github.com/VKCOM/vk-api-schema/blob/master/photos/methods.json)
is version 5.199, blob d461c3f8d72c76b5965bf8a555c9c6558a0ea293.
No documented operation to regenerate an existing photo's rendition was found:
photos.restore restores a deleted photo; photos.edit edits caption/location;
photos.copy creates a saved-photo copy. None promises thumbnail repair.
Reattaching the same ID through wall.edit likewise has no such guarantee.
The existing Vibe in-place media-edit path can replace one attachment with a
newly saved photo while preserving other positions, but that is a content
mutation, not an evidenced systemic fix, and was not performed here.

Stop the bounded probes. Do not add encoded-URL changes, reupload/retry loops,
CDN publication gates or access-key persistence from this evidence.
Keep this as a recurrence observation under related VK-media incident
inc_b4ce8452c3997f4c35ffd141 / PR139; do not attach it as a cause or verification
of the unrelated SQLite/performance incident inc_247a251746662872b81bffbc.
Net production-code changes for this investigation: **0**.
