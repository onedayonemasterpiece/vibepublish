# MAX Web — active runbook

Updated: 2026-09-08. Branch: `work/vibepublish-max-web-20260904`, [PR #2](https://github.com/onedayonemasterpiece/vibepublish/pull/2).

**Status:** Implementation Not done. Product target and current owner instructions are in [MAX product completion for Codex](../handoffs/max-product-completion-codex-20260908.md). That document supersedes older MAX/recovery handoffs as an execution instruction.

## Product target

VibePublish must expose MAX through the normal `MCP → core/application → worker → ProviderAdapter → RealMaxDriver → MAX Web` path.

Required supported lifecycle, where the actual MAX surface allows it:

- publish text, links/formatting, images/albums and supported video;
- exact native readback;
- edit without losing media;
- native schedule, read scheduled state, reschedule while preserving content/media, cancel;
- delete published objects;
- supported reply/reaction/forwarding operations;
- crash/restart/reconcile without duplicate external effects.

A green fixture suite is evidence, not acceptance. Live acceptance is required in the owner-authorized MAX targets.

## Current implementation baseline

PR #2 already contains substantial MAX work: real session/navigation/read paths, `RealMaxDriver`, browser regressions, crash/reconcile qualification, exact native-reference handling, scoped Gemini Lite visual assistance, and actual-core integration tests. Treat these as assets to continue, not as completion.

The independently implemented shared-core recovery/finalization is now available in
PR #1 (`f34ad34caf342966239209a171ef58b06b3bc201`). The MAX bridge accepts
core-admitted immutable original-attempt evidence and releases only its matching
profile fuse after durable core resolution. Missing/different admission never
turns an observation-only recovery into a mutation or release.

Live evidence in the authorized Test Group (2026-09-08 local time):
- Original stuck publication: actual MCP reconcile + worker returned `verified`,
  original attempt preserved (one dispatched attempt), finalize journal `done`,
  exact fuse released, zero new Send. A subsequent reporter SQLite I/O failure
  was separately audited: fresh connection integrity `ok`, durable success intact.
- Original object: normal MCP publication delete + worker + this RealMaxDriver
  verified deletion for everyone, same native identity, finalization completed.
- New ordinary unmarked plain text: actual MCP publish + worker verified native
  URL/content through repeated fresh reads and completed finalization.
- Exact item read through MCP/worker succeeded after replacing positional row
  iteration with semantic candidate rebinding and native-ID verification. Unrelated
  unsupported rows cannot prevent a positive exact-item read; a missing/unverified
  requested item still fails, never masquerades as a proven absence.
- Plain text full chain completed: publish → exact read → edit → exact read →
  delete of the same native object, all through actual MCP/worker, all `verified`
  and finalized. The first edit was blocked before dispatch because the observed
  group heading is `Редактирование сообщения`, not the channel's heading; this is
  now replay-tested. A fresh exact `item_ref` was adopted through the public API
  for the successful edit after that pre-effect failure; no second Send occurred.
- Media/native-scheduled/social completion is NOT claimed by these results.

Production wiring is explicit `existing_session(..., live_writes=True)` into the
same `MaxAdapter`; no second driver, auth path, direct MAX API or local scheduler.
The allowlist still limits these immediate mutations to `test_group`. Without
that trusted wiring the historical observation-only gate remains. Plain deletion
requires a native-copied own object, observed `Удалить сообщение` dialog,
`Удалить для всех?` checked, durable checkpoint and dispatch before one trusted
confirmation. The exact connected-row removal is persisted before fresh absence
checks; absence alone cannot authorize deletion recovery or finalization.

Known unfinished product areas include complete production lifecycle qualification,
media lifecycle, native scheduled lifecycle and remaining supported social operations.

Fresh-read actual PR HEAD/code/CI before changing anything; historical SHA values in old comments are checkpoints only.

## Recovery semantics

An internal uncertainty state may exist temporarily after an external effect when its receipt is lost. It must **not** become a permanent dead end when MAX can be observed.

For MAX, the expected recovery flow is:

1. durable intent/checkpoint before effect;
2. one external effect;
3. normal DOM/native readback;
4. if UI observation is technically ambiguous, optional scoped vision assistance;
5. fresh native readback;
6. durable binding of evidence to the original operation/attempt/plan;
7. terminal core resolution or exact compensation outcome;
8. normal release of the corresponding profile fuse/quarantine;
9. restart repeats observation/resolution, not the mutation.

Do not fix this by manual SQL, deleting the fuse, inventing a receipt or performing another Send.

The original marked Test Group post that previously remained tied to `outcome_unknown` is a required real recovery case. Reobserve it, resolve the original operation through the implemented core path, then clean it up through the normal MAX lifecycle.

## Historical source-write refusals are not an active engineering blocker

Earlier PR comments and old handoffs record source-write/safety refusals from particular ChatGPT sessions for particular attempted payload delivery. They are retained in Git history as provenance.

They do **not** prohibit Codex from independently reading the current repository and implementing the missing core recovery or other required functionality. The owner explicitly authorizes core and MAX development by the same Codex task.

Do not copy/replay/reconstruct a previously rejected payload merely to evade a platform decision. Instead, write the required implementation independently from the current code and product requirements.

Only a new, current, reproduced platform refusal in the active Codex session can be reported as a platform blocker. It does not justify stopping unrelated work.

## Branch ownership

Use the existing work, not a third implementation:

- PR #2 / `work/vibepublish-max-web-20260904`: MAX-specific driver, session/profile, selectors, bridge/wiring, tests and this runbook.
- PR #1 / `work/vibepublish-core-20260904`: shared core/worker/storage/application/provider-port changes when required.

The old restriction that the MAX executor may not modify core is superseded. Codex may work in both existing branches for this product task.

Keep Telegram/VK compatible. Do not duplicate common idempotency/history/dispatch logic inside MAX.

## Live permissions

### Тестовая группа

Owner authorizes all necessary test social operations without additional confirmation and without a test-object count limit:

- publish/read/edit/delete;
- media;
- native schedule/read/reschedule/cancel and actual scheduled output;
- supported reply/reaction/forwarding;
- crash/restart/reconcile;
- repeated cycles and cleanup of task-owned test objects.

Do not alter membership, permissions, group identity/auth settings or other people's messages.

### Ух ты, Калининград! / Полюбить Калининград Анонсы

Current narrower permission remains: read existing feed/queue and create/read/edit/reschedule/cancel **own safe test scheduled items**. Do not intentionally publish an immediate test into the real feed without a later explicit owner instruction.

A failure or ambiguity in one real channel must not stop Test Group work.

## Session handling

Reuse the existing authorized MAX browser profile/session on DevCoveer when valid.

- no logout or cookie/storage-state reset;
- no duplicate Chromium ownership of the same profile;
- no QR/login work unless the existing session actually expires;
- resolve account/chat/native item identity before effects;
- derive production selectors from observed MAX Web, not synthetic test attributes.

If auth is genuinely expired, return a concrete `needs_auth` prerequisite and continue all code/replay work that does not require it.

## Optional visual recovery

`RealMaxDriver` may use the existing scoped visual assistance for technical observation failures.

Rules:

- DOM/native verification first;
- screenshot only the task-owned object/necessary region, not unrelated conversations/settings;
- use `google_ai.GoogleAIClient` and the shared limiter; no direct provider bypass;
- the owner previously authorized local gateway configuration from `/home/dev/projects/my-data-hub/.env`; never copy secrets into Git;
- model output is supplementary evidence only and cannot itself authorize mutation, release quarantine or create a native identity;
- after vision, perform a fresh native readback and let core persist/resolve the operation.

A successful Gemini read is not product completion; continue to terminal operation resolution and lifecycle acceptance.

## Acceptance matrix

Before declaring MAX ready, obtain real evidence through the normal MCP/worker path for at least:

| Case | Required proof |
|---|---|
| plain publish | one native effect, exact readback |
| media publish | exact media/content readback |
| edit | same native object, new text, media preserved |
| delete | exact own object absent after deletion |
| native schedule | queued natively with exact timestamp |
| reschedule | same own scheduled object/content/media, new timestamp |
| cancel | exact own scheduled object removed |
| native output | scheduled effect occurs while VibePublish is stopped |
| crash after effect | restart resolves the same operation with no duplicate mutation |
| original stuck operation | old object rebound to original attempt, terminally resolved and cleaned up |
| supported reply/reaction/forward | native readback proving the supported operation |

If MAX does not expose a listed capability for the tested surface, record live capability evidence and continue the rest.

## Tests and evidence

Keep useful existing fixture/replay tests, but add regressions for every real UI issue discovered.

Required final verification includes:

- MAX-focused browser/adapter tests;
- actual `MCP ClientSession → worker → ProviderAdapter` integration;
- crash/restart scenarios;
- common core/contract tests affected by shared changes;
- exact-SHA GitHub CI;
- remote readback of key committed files/SHA;
- private live evidence under `artifacts/`, never committed if it contains account/session/native/private data.

Do not stop on a progress report. Stop on product acceptance or on a new, reproduced external blocker that truly prevents the remaining path.

## Historical documents

The following are history only and must not override this runbook or the 2026-09-08 task:

- `docs/handoffs/max-web-live-completion-20260905.md`;
- `docs/handoffs/max-core-recovery-completion-20260907.md`;
- old PR comments describing missing ZIPs, prior executor ownership limits or prior ChatGPT source-write refusals.

Git history and PR discussion preserve their evidence; they are no longer active routing instructions.

### Observed read regression reference

The exact-read fix follows the [Playwright locator contract](https://playwright.dev/python/docs/locators):
`nth()` can resolve to a different element after the list changes. MAX history
scrolling/rerendering made positional enumeration unsuitable. Snapshot candidate
text is only a locator aid, not identity: each returned object still requires
native copied-link identity and a second fresh confirmation. No provider API or
application internal state is used.

### Standard worker configuration

In an assembled core/MAX install, the native worker's MAX factory is
`adapters.max.live_session.configured_adapter(connection_id=..., env=...)`.
`VIBEPUBLISH_MAX_PROFILE` is an explicitly supplied private JSON object with
absolute `profile`, `executable`, `allowlist` paths, `live_writes: true`, and optional
`timeout` (1–120 seconds). No defaults, profile discovery, QR, auth copying or
credential borrowing occurs. The existing allowlist/account checks and exclusive
profile lifetime remain mandatory. Core must include the additive native-factory
seam in PR #1; older core intentionally leaves MAX unwired.


### Native image evidence and current live verification (2026-09-08)

Image Send uses the observed **Загрузить файл → Фото или видео** file chooser
and binds ordered filename/blob previews and input digests before dispatch.
The native message menu must be opened on the caption, not the centre of an
image tile. History readiness and lazy photo mounting are distinct from header
readiness; photo tiles determine expected media count. Candidate rejection must
not press Escape without an open menu (MAX otherwise leaves the chat).

Rendered `i.oneme.ru` URLs rotate between navigations and are **not** attachment
identity. The driver opens each exact message's ordered photo tiles and uses the
native viewer's **Скачать** action. Bounded decoded-image validation and SHA-256
of actual downloaded bytes yield typed `DownloadedMedia` evidence. These hashes
are not claimed equal to original uploaded PNG hashes (MAX may transcode JPEG).
The real core `bind_download_media` validates the durable original-intent/native
reference/ordered-download binding. No fake provider IDs, direct CDN requests,
second idempotency ledger or manual quarantine reset are introduced.

Live through actual MCP and standard `worker --native --once`: the initial image
operation recovered without another Send, then exact read → edit → exact read →
delete of that same object all reached `verified` with `operation_complete=true`.
The downloaded image evidence before/after edit was identical. Private receipts:
`artifacts/codex/max-product-20260908/image-{recovery,read,edit,read-edited,delete}-status.json`.
A subsequent fresh two-image album also completed publish → read → edit → read
→ delete through the same MCP/standard-worker path, all verified/complete, with
both ordered downloaded proofs unchanged after edit. Its private receipts are
`album-{publish,read,edit,read-edited,delete}-status.json` in the same directory.
This is image/album lifecycle evidence, **not** completion of video/native
schedule/social acceptance. Those requirements remain Not done pending their
own live checks. Requires the additive typed-download/read projection in PR #1.


The additional **MAX with pinned actual core** CI job assembles only the MAX
adapter/tests onto exact core `7deab3e92b3f97330b0fface39656980ed3332c1`
from existing PR #1, and requires the genuine MCP/worker suites without missing-core
skips. It does not merge or vendor core into PR #2. The original MAX-only job
remains separate. Both jobs use offline provider replays, not live browser access.


Native queue discovery: the two authorized channels expose the queue and
**Отправить сейчас / Изменить время / Редактировать / Скопировать текст / Выбрать /
Удалить**. Unlike published messages, scheduled rows expose neither a copy-link
menu item nor a native ID in rendered DOM (only positional `data-index`, which
is not identity). No existing channel queue item was changed during discovery.
Schedule clock spinbuttons were live-confirmed to respond to ArrowUp/ArrowDown;
no schedule confirmation was clicked in that read-only form inspection.


### Video verification (2026-09-08)

The observed video upload preview is a data-URL placeholder (not the image blob
preview) and **Отменить загрузку** disappears when upload completes. Readback
counts direct media tiles, not their nested player-control buttons. Keyboard
Enter on the exact outer tile opens the native viewer without the nested
pointer overlays; its download action is **Скачать видео**. The existing shared
core video validator performs bounded H.264/MP4 decode/probe; hashes describe the
original downloaded bytes, not the sanitized ingress derivative or a signed URL.
A native copied reference is checkpointed before inspecting the video download.

Actual MCP/standard worker: original video publish was recovered read-only after
the initial missing-video-reader result, without another Send. Exact read → edit
→ exact read with identical video evidence → same-object delete then all reached
verified/complete. Private `video-*-status.json` receipts are in the same task
artifact directory. A subsequent fresh video also completed publish → read → edit → read → delete
without any recovery command; all five receipts were verified/complete. Runtime
driver blob matched remote commit `346dff0b898b9cd4ef70811e1262915122189c11`.
Offline MP4 replay uses a small locally generated geometric clip, not private
MAX media. Video verification requires the shared core and ffmpeg/ffprobe.


### Formatted text and Unicode DOM projection (2026-09-08)

The real editor exposes Ctrl+B, Ctrl+I and Ctrl+K; the observed link dialog is
**Ссылка**, input placeholder `https://max.ru`, **Добавить**. Ctrl+Backslash
(**Обычный**) removes old styles and links before an edit. These are ordinary
keyboard/dialog interactions, not Lexical editor-state or internal API calls.

MAX converts ordinary Unicode emoji into non-editable raster DOM decorators:
`textContent` omits their glyphs and includes loader whitespace. The shared MAX
DOM projection reads the observed `data-lexical-emoji`/emoji image alternative,
uses UTF-16 DOM ranges around whole decorators, and applies core MAX-only font
semantics: exclude neutral emoji-presentation graphemes from bold/italic while
retaining exact text and link spans/URLs. Adjacent same-style text spans coalesce.
Boundary emoji and neutral interior glyphs have regressions; no font weight is
asserted on raster emoji pixels. Telegram/VK semantics remain unchanged.
A registered Playwright semantic selector re-evaluates actual DOM content; it
never adds DOM IDs/attributes, and is not provider identity. Native identity
still comes exclusively from the copied MAX reference. Emoji images in captions
are not attachments. Last-input guards use stable semantic projections rather
than loader-dependent HTML.

Actual MCP/worker: a first rich attempt was blocked **before dispatch** by the
missing emoji projection. The original operation was safely re-admitted through
core `retry_failed` (not a new publish key). Publish → exact read → formatted
edit (including a new link URL) → exact read → same-object delete all subsequently
verified/complete. Unicode text, bold/italic UTF-16 spans and exact labeled link
URLs were present in the real MCP read projections. Private `rich-*-status.json`
receipts remain task artifacts. Only bold, italic and labeled-link recipes are
currently qualified; other rich recipes remain explicitly unqualified rather
than silently stripped. Native scheduling and social acceptance remain active.

### Native queue evidence implementation (2026-09-08, acceptance in progress)

The queue has no DOM item ID or copy-link menu. It is now read through normal
MAX Web UI, passively correlating history response opcode 49 to the browser's
original request by owned page/socket/sequence, exact chatId and itemType DELAYED.
Opcode 71 is **not** a queue list (it reads selected feed items); it is ignored.
Only the factory's own UI/account pages are observed; no recovered tab, auth
frame, app store, direct MAX request or traffic mutation is used. Received
native IDs/times are cross-checked against exact visible content/time and a
second independent page-load/queue response. A full response page is not treated
as a complete queue. Read-only live qualification matched four native queued
objects twice on an authorized channel with zero social effects.

Fresh boundary-emoji rich lifecycle also passed through MCP/native worker:
publish → exact read → formatted edit → exact read → delete, all verified and
complete. The same native object was deleted; this cycle needed no recovery.
Core MAX font projection is in PR #1; Telegram/VK comparisons are unchanged.
Native schedule publication, media-preserving changes/cancel and social cases
remain under active acceptance; this section is not full product closure.

Actual MCP/native worker scheduled an image once, then recovered its exact
native queue ID/time/media without another Send. A pre-existing unversioned v0
attempt was separately cancelled by checkpoint-bound proof that its explicit-role
DIALOG guard made input unreachable, not by treating absence as publication.
Core preserves historical dispatch and finalizes compensation durably.

Actual reschedule changed the scheduled native item ID while retaining exact
text/image bytes and moving the native time by two hours. The original operation
was resolved read-only through MCP/worker as scheduled/complete; no repeated Save,
no manual database write or fuse removal. Recovery requires the persisted trusted
Save (or pre/post native correlation), a unique native queue replacement and two
fresh exact time/content/download checks. Typed core replacement evidence keeps
logical publication/attempt lineage and post-commit finalization releases only
that attempt. Missing or ambiguous evidence does not authorize another effect.

Native `<dialog>` has an implicit ARIA role: last-input guards must include the
native tag, not only `[role=dialog]`. Group queue heading is **Отложенные сообщения**,
not the channel heading. These observed distinctions have offline regressions.
The shared dependency pin now includes native replacement/no-effect/finalization
support. Local core validation: 233 tests + 202 subtests; focused replacement
algorithm 5 tests. Broader MAX replay regression is running separately; native
cancel/edit/output and social acceptance remain **Not done**.
