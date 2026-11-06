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
