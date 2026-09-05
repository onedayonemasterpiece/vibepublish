# Telegram custom emoji — sets, visual choice, sequences and native entities

> Current remote delivery: **partial, not a runnable release**. The implemented
> behavior and historical test counts below describe the complete archived source.
> Three production modules remain undelivered; current evidence and exact boundaries
> are in [runtime status](../../operations/social-runtime.md).

Date: 2026-09-05. Owner requirements: **Fixed**. Detailed design: **Draft / Not confirmed by user**. Offline runtime: **Implemented / Not confirmed by user**. Live Telegram capability/visual canary: **Not done**.

This feature belongs to the existing social publication pipeline, not an independent post-editor service. It extends the existing canonical eight MCP task methods. It must preserve the current native-only scheduling, durable operation identity, immutable execution plans, provider readback and existing worker core. The established core is not to be rewritten as an emoji-only scaffold.

## 1. Owner intent

The user supplies one or several Telegram custom-emoji sets, sees what they actually contain, chooses either one emoji or an exact ordered chain/composition, assigns reusable meanings, and uses those choices in later publications. Candidate discovery and bulk replacement must be convenient without requiring the model or person to manually calculate native document IDs or UTF-16 offsets.

Required user paths:

1. Give a `https://t.me/addemoji/<set>` link; inspect the actual set rather than infer its contents from the name.
2. See a numbered contact sheet/picker with stable item references; select a single symbol by its visible appearance.
3. Select an explicit ordered chain, for example the two different halves of the Tretyakov building or the four-letter FREE composition. A chain is a first-class reusable object, not one opaque emoji with an assumed length.
4. Save a personal alias and optional replacement rules; use the same meaning in later posts or deterministically replace the approved ordinary Unicode triggers throughout a draft.
5. Preview and approve the exact resulting content. Initial publish, captions, supported edits and native scheduled items must preserve the chosen custom entities without a delayed after-publication rewrite.

The primary interface is conversational/MCP with visual previews; a separate large emoji-management application is not a prerequisite. A small protected preview resource is acceptable. Plain JSON describing images is not sufficient evidence that the actual appearance was shown to the owner.

## 2. Actual donor evidence read

Fresh donor revision inspected: `events-bot-new@b8f463f5c35fa62befcfed171a7a8a0886af20f7`. These are source/provenance observations, not a claim that donor or live tests were rerun in this design turn.

| Source | Observed behavior or lesson |
|---|---|
| `tg_premium_emojis.py`, blob `6329dcf72c0314523d3616a01ca464829fbb320c` | Telethon custom-emoji transformations; single mappings, free-label sequences, venue-specific two-part composition, cloning/shifting existing entities, preserving covering bold/text links, checking already expected entities. |
| `tests/test_tg_premium_emojis.py`, blob `11cf9eeeeb647a1b750f825883cf9709fa5798b6` | Existing regression intent for exact two-part Tretyakov IDs, FREE sequence, rich formatting preservation, idempotence and removal of stale title-level custom entities. |
| `.codex/skills/tg-premium-emojis-update/SKILL.md`, blob `62363dfeb4a395eedfdf608c8859524e808729e2` | Fetch real sets, group by their ordinary Unicode alternative, show candidates before choosing, consider adaptive/repainting sets, then update a deterministic mapping and verify native readback. |
| `docs/reports/incidents/INC-2026-06-29-tg-premium-tretyakov-composite-pair.md`, blob `130499a4e6767112c0b824748093f25a67af8460` | Same fallback `🖼` represented a small standalone thumbnail and two adjacent composition parts. The incorrect fix duplicated the thumbnail. Presence of two entities alone was not a valid test; exact distinct IDs and order were required. |
| `docs/reports/incidents/INC-2026-06-30-tg-premium-custom-medallion-symbol-too-compressed.md`, blob `b3c4f11d09772b0c0243a8069e810c1c397f4719` | A tiny emblem can be technically valid but visually unreadable at emoji size. Upscaling a preview does not establish readability in Telegram; preserve the original asset/canvas and validate native-size appearance. |
| `main.py` / `main_part2.py` donor callsites | Existing donor workflow scheduled a premium-emoji editor after daily/weekend publication. This architecture is not to be copied: VibePublish should compile the approved entities before the first native send. |

Known donor regression fixtures: Tretyakov composition is the ordered pair `5188445640325099838`, `5188470637034758005`, not twice the small thumbnail `5188683852096234620`. The FREE chain is `5406749623865857008`, `5407072545276973461`, `5406815783542085177`, `5406927577245833438`. These IDs are useful fixtures and optional user-confirmed catalog choices, **not global defaults silently installed in every tenant's palette**.

### Reuse and correct

Reuse deterministic operation ordering, preserving covering formatting/link entities, explicit per-context rules and an idempotent no-change second pass. Extract the reusable transformations into VibePublish with local tests and provenance; do not import EventsBot runtime, scheduling code, environment credentials or its business-specific venue rules.

Do **not** copy the donor's fixed `length=2` / `index*2` assumption. UTF-16 length comes from the exact approved fallback span per part. Variation selectors, BMP symbols, regional indicators, modifiers and ZWJ sequences must not be cut, normalized away or assigned fabricated offsets. Do not select a composition by “two first matches with the same Unicode”; display and bind the real parts individually.

## 3. Product workflow and states

### A. Add or refresh a set

Accept an exact Telegram `addemoji` URL or an already authorized set reference. Resolve it with the selected user's authorized Telegram connection. Do not follow arbitrary URLs or join chats. Enumerate native set metadata and documents in returned order; verify that it is an emoji set, not an ordinary sticker pack. Reading a set is not authorization to install/subscribe to it in the user's Telegram account.

Persist a private immutable catalog revision: native set identity/short name, provider hash/revision where available, observed_at, document IDs, exact `alt`, free/premium/repainting/animation metadata and verified preview assets. Refresh creates a new catalog revision; it never changes an old selected chain or approved publication behind the user's back. Removed or inaccessible documents become unavailable for new selection rather than silently replaced by “similar” ones.

A set can be large. Bound fetch/page size, file bytes, decompression, thumbnails and total preview area. Return an accepted receipt for remote reads; render only a bounded page, with cursors and exact numbering mapped to opaque item refs. Set resolution/fetch/preview stages use the existing progress mechanism and current access checks.

### B. Show actual media, not labels alone

A preview contains the set title/revision, page/row/column or visible number, the actual image/animation and an unambiguous item handle. For animated/vector/video custom emoji, use a verified native thumbnail/preview or a safely rendered local derivative with explicit frame/provenance. A Unicode placeholder must not masquerade as the selected design.

A contact sheet helps a model/person choose among candidates; a one-item preview and an assembled multi-part preview help check detail and seams. Preserve the exact part order and explicitly show repeated parts if the user intentionally requests them. Do not automatically deduplicate a composition. Large preview and native-size samples serve different purposes: readability at the actual Telegram size is a separate acceptance check.

Previews are private assets protected by the same principal/tenant/binding rules as other VibePublish assets. A display token or image URL is not a general-purpose access grant. No public permanent URL is required for private palettes. Signed/short-lived browser resources may be added through the existing asset delivery mechanism; private HTTP/MCP resources remain valid internal routes.

### C. Select a single item or ordered sequence

Selection binds the exact catalog revision plus an ordered list of item handles/document identities. Resolve ordinal choices such as “7, then 8” only against the just-shown revision. A reordered/refreshed set must produce a stale-selection error, never a different implicit choice.

Persist a personal `emoji_alias` (name, semantic description, selected parts, fallback text, revision, source catalog refs). A single emoji is a one-part chain. A multi-part chain stores each native ID and that part's exact fallback/alt; concatenated fallback text and spans are derived, not guessed. New alias revisions are immutable. A publication plan stores the resolved parts/IDs and revision, not just a mutable alias name.

Telegram line wrapping and animation timing can affect how a long chain looks. The preview must not promise one-line layout on all clients. Before a real canary, verify the chosen short composition in actual Telegram; do not claim browser-only assembly is identical to native emoji rendering.

### D. Reuse and optional bulk replacement

The existing content tree already has an `emoji` inline alias. Resolve it before provider dispatch into a frozen semantic custom-emoji span/chain. The model provides a known alias, not raw entities or Telethon kwargs. Direct selection inside a draft can be represented by an immutable selection ref, following the same validation; avoid a second free-form native-ID entry point.

Optional rules map an exact trigger/context to a personal alias, with explicit priority and enable/disable state. Context can be a semantic location/venue/category from structured input, not an arbitrary model-inferred substring match during execution. Alias reuse is not permission to globally replace every visually similar glyph.

The deterministic compiler must:

- use normalized deterministic matching boundaries but preserve exact source and chosen fallback codepoints; never mutate URLs, native entity internals, code/pre blocks or unrelated existing custom emoji;
- prefer the longest non-overlapping trigger and resolve equal-priority conflicts explicitly, not depend on dictionary iteration order;
- preserve supported formatting and link entities across replacements, shifting offsets and lengths by actual UTF-16 delta; reject ambiguous partial overlaps instead of silently dropping content;
- leave unknown ordinary emoji/text intact; preserve existing correctly bound custom entities; apply correction of wrong/stale custom IDs only under an explicit matching rule or approved edit;
- be idempotent: compiling an already compiled content snapshot yields identical text/entities, zero additional changes, and the same semantic fingerprint;
- return a preview/change summary and exact resulting semantic spans. Choice/palette/rule changes create a new publication revision before approval.

V1 should support explicit alias insertion and exact Unicode/text replacement first. Free-form semantic classification or model-selected rewrites are optional future draft transformations and must not run inside execute/reconcile.

## 4. Native provider contract and readback

For Telegram, a custom emoji entity refers to a native document ID and an actual span of the ordinary alt in the message text. Use the real Telegram TL types when the SDK is installed; the public model surface never sees provider request internals. Compile structured text/rich entities once into the immutable execution plan, including caption entities for supported media paths. Preserve original source entities during a native forward; do not apply rewrite/palette rules to forwarded content by accident.

The archived Telegram adapter currently accepts only plain content and `_item` does not yet expose entity observations. Thus this is a real core/adapter/readback change, not merely adding a schema alias:

1. Add a backward-compatible optional semantic-entity observation field to the existing core port; coordinate it with the separate MAX bridge instead of creating a second port.
2. Persist approved content entities in plan and actual entities in provider observations; include semantically relevant custom IDs/spans in the identity/CAS and verification digest. Text equality alone is insufficient.
3. Extend Telegram compile/readback for text, captions, supported edits and native queue reads; use exact native IDs/order/spans. Preserve the existing dispatch/checkpoint/reconciliation contract and native identity handling.
4. An absent/different custom entity is a readback mismatch or explicit unsupported state, not verified success and not a reason for an automatic second send.

The exact live capability depends on connection/account type and Telegram eligibility. The Bot API has separate custom-emoji requirements; user Premium status and per-document free flags matter on MTProto paths. Inspect the actual account/document/surface capability and fail explicitly when unavailable. Do not reuse an EventsBot premium session or another user's entitlement. Do not silently downgrade the user's chosen composition to ordinary placeholder emoji.

Read current Telegram configuration/capability limits, including the maximum custom-emoji count per message where applicable. Reject or request an explicitly approved simplification when exceeded; do not split a publication automatically. Scheduled posts must carry the correct entities when first enqueued, and later edits/reschedule must preserve them.

VK and MAX do not acquire Telegram custom-document semantics. For a multi-provider post, each destination needs either an explicitly approved ordinary-text rendering/fallback or a typed review/unsupported result. A Telegram-only visual decoration must not be accidentally pasted as raw HTML/native IDs or trigger another silent lowest-common-denominator rewrite.

## 5. MCP grammar, not a new tool family

Use the existing `destinations` method for bounded palette/set configuration and immutable selection, `read` for set/palette/catalog inspection and private preview references, `publish` for using existing aliases, and `publication_update` for revising a draft/post. A generate-image tool is not required to browse real Telegram emoji.

Possible discriminants (to finalize in the implementation rather than copy as already live): `emoji_set_register`, `emoji_catalog`, `emoji_alias_select`, `emoji_rule_put`. Keep closed command objects and concise required fields. A caller sends the actual set URL, catalog/selection token, exact ordered choices and alias/revision; it never supplies `document_id`, UTF-16 offsets, raw SDK request names or a generic provider-options bag.

The canonical `get_started` skill must teach: add set -> inspect the numbered actual preview -> choose one or several exact parts -> save alias/rules -> preview resulting publication -> publish -> observe native readback. It must explain stale selection, unknown outcomes, meaningful fallback and a single parent operation. Do not introduce a ninth synonym/bootstrap method. API, MCP prompt/resource and skill text share one application service and one schema source of truth.

Updating the payload grammar requires a minor contract/skill version bump, exact examples, schema tests and the existing forwarding/profile scope projections. `destination.profile` permission alone must not enable another principal's palette; configuration stays personal and no selection grants a provider binding.

## 6. Acceptance tests to implement

| ID | Required automated evidence |
|---|---|
| E01 | Resolve actual-shaped emoji-set metadata; reject ordinary sticker-set links/type mismatch, wrong target connection and malformed URLs; no account subscription operation. |
| E02 | Numbered paginated previews map each actual image/asset to a stable catalog entry; missing/oversize/invalid thumbnails fail honestly; private assets cannot be read by another principal. |
| E03 | Selecting one item or an ordered chain freezes catalog revision, exact native IDs, part order and fallback spans; stale/reordered catalog and cross-owner tokens rejected. |
| E04 | Regression: distinct Tretyakov pair, not duplicate thumbnail; exact FREE four-part order; explicit repeated parts retained; no accidental source/candidate dedup. |
| E05 | Unicode/UTF-16 cases: BMP and supplementary symbols, variation selectors, modifiers, flags, ZWJ sequences and mixed-width chain parts. No fixed 2-unit offsets. |
| E06 | Preserve bold/italic/links and caption content; skip code/URLs/unknown emoji; ambiguous partial overlaps fail, not silent deletion. |
| E07 | Longest-match/conflict policy, deterministic rule ordering and idempotent second pass; no growth of entities or drift in content fingerprint. |
| E08 | Alias/rule/catalog revision change after preview does not alter frozen approved plan; explicit revision required for new selection. Revocation invalidates previews/readback/caches. |
| E09 | Actual Telegram adapter emits native custom entities on the first send/enqueue and supported edit; forwarding preserves source entities; no post-send delayed editor and no second scheduler. |
| E10 | Native readback missing/wrong ID/order/span fails verification and becomes unknown as appropriate; lost response/restart reconciles without another send or emoji-only repair write. |
| E11 | Non-Telegram explicit fallback/renderings and unsupported paths are deterministic; mixed child outcomes preserve prior provider successes. |
| E12 | Actual MCP ClientSession + worker + private preview resource workflow, fixed exact IDs and a browser contact-sheet/chain preview; fake/native/live evidence distinguished. |

Add these to the existing suites/CI, not a second verification project. A real Telegram canary must use an explicitly authorized test destination and verify native-size appearance, entity IDs/order, text/caption/native queue readback and no duplicate send after restart. No live writes are authorized by this design document.

## 7. Current boundaries and related work

Full archived core/native/VisualService implementation remains preserved separately; its GitHub delivery/locked CI is still a prerequisite, not a reason to rebuild it. MAX already has its own PR/task; do not duplicate its development. Imagegen binding follows this emoji slice and targets **local Codex on DevCoveer**, not the owner's personal computer and not an assumed OpenCode plugin. Direct image-tool invocation is permitted when separately authorized; development stays in ChatGPT.

### Primary Telegram references checked

- https://core.telegram.org/api/custom-emoji
- https://core.telegram.org/constructor/messageEntityCustomEmoji
- https://core.telegram.org/constructor/documentAttributeCustomEmoji
- https://core.telegram.org/method/messages.getCustomEmojiDocuments
- https://core.telegram.org/api/config
- https://core.telegram.org/bots/api (custom-emoji message entity and account-specific eligibility)

These references constrain the implementation; they do not establish that the user's actual session/set/live target has been inspected in this design turn.


## Implemented offline slice (contract 1.5), 2026-09-05

The preceding design is now backed by `social_operations/emojis.py`,
`rich_text.py`, `emoji_preview.py`, `adapters/telegram_emoji.py`, migration 3 and
additive `RemoteItem.entities_json` (default `[]`). `adapters/telegram.py` sends
native semantic entities on the initial text/photo/album send and edit; reads
and native schedule readback compare exact normalized entities, not just glyphs.
Native item identity includes nonempty entities; old plain/MAX fingerprints are
unchanged. MAX's existing bridge can keep the default and continues to reject
rich content until its owner explicitly implements it. No MAX code is changed.

Implemented command details are canonical in `contracts/social_mcp_v1.py`:
register an exact supplied set link with a bound Telegram alias/revision; inspect
actual thumbnail files/contact sheets; select ordered numbered cells against
catalog_revision + short-lived selection_token; save revisioned alias and explicit
rules; use existing semantic inline emoji aliases in publish/edit. The protected
`/v1/emoji/catalogs/{catalog_ref}` page shows actual sanitized media and emits a
pending typed command for the chosen single/chain/repeats. It does **not** itself
save or submit. Preview images and HTTP/MCP assets recheck current access.

Rules use literal matching, semantic venue/category context, longest match and
explicit equal-overlap rejection. UTF-16 offsets follow each exact part alt;
format/link containers adjust, ambiguous partial overlaps block, code/URLs are
excluded. Compilation and approval snapshots are idempotent and immutable.
Non-Telegram chains need `emoji_fallback: approved_text` using the alias's meaningful
fallback; missing render-only fallbacks block that child without discarding an
otherwise successful Telegram child. This narrow exception does not remove the
existing all-target safety/capability preflight for other failures.

MTProto eligibility reads the actual configuration limit and selected document
metadata before mutation. Nonpremium accounts need free documents. Unknown/
changed/deleted IDs, invalid metadata, unsupported bot custom-emoji paths and
limit excess block before the effect. Forwarding retains original entities and
attribution; no palette rewrite is applied to a native forward.

Offline evidence is in tests/emoji: real TCP MCP ClientSession/server, original
worker/SQLite, scripted MTProto responses, actual local Chromium preview checks
at 1440x900 and 390x844, exact synthetic-media provenance, native request/readback
fixtures and recovery tests. Synthetic images are explicitly labelled fixtures,
not photographed live Telegram pack contents. A separate real SDK serialization
gate exists at scripts/verify/telegram_sdk.py and must run in an environment with
the actual pinned Telethon package.

Remaining restrictions are explicit: at most 200 entries/set, 50/page, 16 parts/
chain, 100 stored catalog revisions and 1000 alias/rule revisions per principal,
16 MiB aggregate thumbnail input, 2 MiB per download. Static actual thumbnails
are shown; native animation/repaint/native-size seam behavior remains unverified.
No auto-install/subscribe, paid bot path, cross-owner palette, live Telegram canary,
external media replacement or arbitrary provider/entity passthrough is enabled.
