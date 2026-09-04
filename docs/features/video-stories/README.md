# Video stories / editorial generator

Status: `Draft` normalization of existing owner text; implementation `Not done`. Source requirements are preserved verbatim in [the original backlog](../../backlog/requirements.md). This section does not silently discard or declare completion of that product.

## Scope and boundary

VibePublish also includes a Telegram-controlled video-story generator. It selects footage, accepts text/voice editorial comments, prepares a short story, renders on Kaggle, presents an approval preview and then uses the **same social publication service**. It must not create its own Telegram/VK/MAX credentials, independent sender, scheduler or retry ledger.

A generated video is an immutable asset with provenance. Editorial generation never implies permission to publish it. EventsBot `/kenigsberg` and related workflows are donors to inspect before implementation, not live dependencies to import wholesale.

## Preserved owner requirements

- Separate Telegram control bot on the same service host; dedicated namespaced environment/secrets and model-limit control.
- Final 720p video with subtitles; story text fits a maximum 55-second video and avoids generative boilerplate.
- Best footage segments rather than indiscriminate concatenation; cuts synchronized with strong music beats where feasible.
- Music selected from an eligible dataset, randomized only after rights/surface/time eligibility checks; selection seed and source recorded.
- Kaggle is the render execution environment. Debug scenarios use no more than three footage clips.
- A story accepts multiple text and voice comments; voice is transcribed, attribution retained and edits accumulated into a versioned brief.
- Extract coordinates from uploaded footage when present; coordinates remain private source metadata unless explicitly included in an approved publication.
- Allow geographic and time/season-dependent selection: current location or representative coordinates from a chosen clip set; today's clips, all dates or a season across years.
- Nearby Wikipedia/Wikimedia candidates are suggestions, not facts automatically injected into the script. The user can approve/filter them with checkboxes before script generation.
- Enhance the assembled footage before adding subtitles, preserve fps/duration/audio and avoid default aggressive AI enhancement.
- Mandatory preview/approval before posting to stories/channels.

These are product requirements, not a claim that all corresponding integrations already exist.

## Chosen workflow for implementation

```text
story draft + authorized footage set
-> source metadata / geo / temporal filter
-> candidate clip shortlist + nearby-place suggestions
-> user approves relevant sources
-> accumulated text/voice comments -> versioned script
-> timing and rights validation -> edit decision list
-> Kaggle render job
-> concat/cuts -> safe enhancement -> subtitles -> final QC
-> protected preview -> approve exact asset + destinations + schedule
-> ordinary VibePublish publication
```

The story object owns source IDs, footage selection policy, geo/time filter, approved nearby candidates, comments/transcripts, script revisions, edit decision list, music source/rights, render job reference and accepted output hash. Render attempts use the common durable task/operation infrastructure. Failure or timeout does not launch a second untracked notebook.

Renderer input is an immutable manifest with signed, short-lived asset access; no social credentials. Renderer output is video, thumbnail, subtitle file, technical QC and provenance manifest, with hashes checked on import. Kaggle execution identity and notebook/version are retained. Cancellation/late output are reconciled by job identity. A render result cannot change the selected targets or posting time.

## Video and enhancement contract

Normalize footage into a target canvas before enhancement. Proposed profiles: portrait `720x1280` for stories, landscape `1280x720` where required by a destination. This orientation choice is an engineering proposal, not an assertion that the historical requirement fixed both. Once the canvas is selected, enhancement must not alter resolution, fps or duration.

The full original parameter ranges and `fast_safe`, `opencv_custom`, `ai_optional` modes remain in the source backlog. Do not change them during extraction without a documented delta. Default is mild FFmpeg denoise/sharpen/contrast, audio copy when container-compatible, no default AI face restoration, and no default upscaling. Enhancement happens before subtitle rendering. Encoding compatibility exceptions must be reported instead of silently stripping sound.

QC checks: target geometry; unchanged fps; enhancement duration delta <=0.1s; final story <=55s; audio retained and synchronized; subtitles inside safe regions, readable and consistent with the approved script; no missing footage segments/black frames; temporal flicker review for any AI enhancement. Test render previews visually on desktop and mobile; metadata-only tests cannot certify appearance.

## Approval and rights

Approval binds story revision, actual final video hash, approved music usage scope, concrete destinations and schedule. Changing the script, music, clips, output or target set invalidates approval. Caption-only changes follow publication revision rules. Publication consumes the standard VibePublish receipt and cannot report success merely because Kaggle finished.

Do not infer music, footage or Wikimedia reuse rights from availability or from a model's opinion. Store actual source/license evidence and required attribution. Expired or unknown rights block automatic distribution and produce a review action. Provider music catalog availability remains connection/surface-specific; no universal promise of platform-library access.

## Delivery status and tests

This feature is a separate batch after the dependable social core, not an expansion of the first MCP publishing mutation. The Telegram editorial UI may be implemented first; future MCP editorial tools require their own task corpus rather than overloading `publish` with all video-production arguments.

Required scenarios: upload without GPS; intentionally mixed geography; today-only versus seasonal archival footage; voice correction supersedes earlier script; unchecked nearby landmark excluded; three-clip debug render; no eligible music; rights expiry; render restart/late result; subtitle overflow; enhancement changes fps; expired publication schedule; revoked access after approval; repeated approval publishes only once.

Implementation order: inspect donor `/kenigsberg`; extract source/EDL/render contracts; fake Kaggle job tests; real bounded Kaggle render; visual/technical approval; standard social dispatch. Existing social, imagegen and video obligations must remain separately visible in release status.
