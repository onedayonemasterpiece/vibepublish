# Telegram custom emoji: sets, visual selection and ordered compositions

Date: 2026-09-05. Owner intent: **Fixed**. Workflow/schema details below:
**Draft / Not confirmed by user**. Runtime implementation: **Not done**.
This extends rich content in the existing social-operations service; it is not
an alternative publisher, post-edit scheduler, imagegen job or sticker sender.

## Requirement delta

Already present: the donor map requires custom emoji and the archived contract
contains an inline `emoji` alias. Missing: set catalog, visual selection, ordered
compositions, editable personal replacement rules, real Telegram entity compiler
and semantic readback. In archived `870e2a4304c57ef5dd7152de63df1db6431a942b`,
`adapters/telegram.py` still builds the supported requests with `entities=[]`;
schema acceptance must not be described as custom-emoji runtime support.

Owner requests: add an existing Telegram emoji set by link, visually select one
emoji or a consecutive composition, and reuse deterministic standard-to-custom
replacement. Creating/uploading a new Telegram set is not requested here.

## User workflow

1. User supplies `https://t.me/addemoji/<short_name>`. Register a set in their
   VibePublish palette via an authorized Telegram connection. This does not
   automatically install a set into the Telegram account or change subscriptions.
   Resolve an actual custom-emoji set and its document metadata through Telegram;
   do not fetch arbitrary URLs or assume an ordinary sticker pack is an emoji set.
2. Return a private numbered contact sheet, plus an animated preview where the
   actual media format can be rendered. Each cell is bound to a catalog revision,
   document ID, real alt emoji and preview hash. Same Unicode fallback is NOT
   an identity: different cells may all look like `🖼` in plain text. Static
   thumbnails are labelled static previews, not proof of animation timing.
3. User selects cells: “E03 and E04, in this order, as one sequence”. A user
   screenshot/crop or arrows may propose these cells, but cannot supply invented
   document IDs. Resolve against the fetched catalog; ambiguities require a
   numbered preview and confirmation. Refreshing/reordering a set must not remap
   a stale cell selection to different emoji.
4. Show the selected sequence side by side without inserted spaces, plus its
   alias and ordinary-text fallback. Save a versioned alias such as
   `venue.tretyakov` or `label.free`. Preserve arbitrary explicit order and repeated
   parts; never deduplicate a composition. Do not infer that nearby set entries
   automatically belong together. A single emoji is the same model with one part.
5. Optionally save a deterministic rule: `🎭` -> selected theatre emoji, or exact
   `🟡 Бесплатно` -> the approved four-part label. Rules are scoped to the user's
   palette/editorial profile; enabling them is an explicit choice, not global
   retroactive rewriting. Unknown/unmapped ordinary emoji stay unchanged.
6. On publication, resolve aliases and rules once, freeze the exact ordered IDs,
   alt text and palette revision, and show the final Telegram-specific preview.
   Native now/scheduled submission contains the final custom-emoji entities from
   the start. Changes to the palette cannot change an approved or queued post.

Alternative exact input: an explicitly authorized Telegram message already
containing the desired composition can provide its entity IDs/order. Read only
that permitted message; a Saved Messages example is owner-only unless separately
authorized. Clipboard plain text/screenshots can lose entity identity, so they
are not equivalent inputs. No instruction grants partners access to owner dialogs.

MVP contact sheet/choice can use the current MCP resources and authenticated HTTP
preview routes; no separate editing application is required. Production client
rendering still needs visual checks; no real pack screenshot was fetched here.

## Data and compilation

Keep the existing ledger/SQLite migration system. Proposed records:
- set snapshot: principal/tenant, authorized connection, set identity/revision,
  observed_at, ordered entries and private preview references;
- palette alias revision: ordered parts (document_id as decimal STRING, exact
  Telegram `alt`, source set snapshot, preview hash), semantic fallback/label,
  selection evidence and optional approved deterministic replacement rules;
- frozen publication expansion: alias/rule revision, exact text/entity spans and
  content digest included in preview/approval/CAS/idempotency.

Store external 64-bit document IDs as strings in JSON/JS; never round them through
floating point. Core compiles trusted structured text/runs, not model-supplied raw
HTML/provider calls. Reuse the existing inline emoji alias; no caller-calculated
UTF-16 offsets or Telegram IDs are needed for ordinary use.

For each part, emit exactly one MessageEntityCustomEmoji over its actual alt
emoji. Compute offset and length in UTF-16 code units, including variation
selectors, ZWJ sequences, flags and modifiers; do not use `index * 2` or `length=2`.
Do not split graphemes, change alt to arbitrary text, or insert zero-width joiners
between distinct parts merely to prevent wrapping. Composition is atomic in the
palette/selection model; pixel placement in different Telegram clients is not a
server guarantee. Preview and reflow limits must be honest.

Apply explicit inline choice before approved automatic replacements. Resolve
longest exact rules deterministically; reject equal-priority ambiguity/overlap.
Exclude code/pre, raw URL targets, mentions and protected existing custom entities
from automatic mutation. Use semantic venue/category fields for contextual rules,
not substring matches inside titles or words. Preserve other rich entities and
links with interval remapping; unsupported overlap must block, not silently drop
formatting. This also requires completing the existing rich-content compiler.
Do not reapply rules to already compiled/frozen output.

Fingerprint/revision checks must include text AND ordered semantic entities
(type, offset, length, document ID, link target etc.), not text only. Telegram
readback for now, native scheduled, edit and reschedule verifies the exact custom
IDs/order/spans and unchanged non-emoji entities. Dropped/wrong entities are not
successful rich-content delivery. Native forward preserves provider attribution
and existing entities; do not apply emoji rewriting to a forwarded source.

Multi-target publication keeps the semantic base text. VK/MAX do not acquire
Telegram custom emoji by copying markup. A profile may explicitly approve ordinary
Unicode/text fallback, visible in per-target preview; otherwise report unsupported
for that target without discarding another target's successful result. A visual
word-label fallback should retain meaning, not silently emit four meaningless
fallback symbols where ordinary text is required.

## Account types, access and limits

Capability depends on actual connection/account, destination and selected emoji,
not just a Premium-looking source set. Inspect MTProto user rights, applicable
free/premium/group exceptions and server limits. Bot API, MTProto bot and Business
remain separate types; do not assume a Premium human automatically enables bots
or channel posts. Preserve needs_auth/unsupported/needs_review rather than silently
stripping custom entities. Recheck permission and time before durable dispatch.

A set URL/registration creates no publishing grant. Personal mappings, screenshots
and choice operations are private by default. Partner access to shared palettes
must be explicit and still bounded by existing publishing bindings. Revocation
invalidates preview/cache/cursors/selection tokens; account-owner reads remain
limited to actual connection access. Unavailable/deleted selected documents block
that choice or use an explicitly approved fallback; no “similar-looking” auto-ID.

## Verified donor, not an instruction to run its production editor

Fresh-read `onedayonemasterpiece/events-bot-new/main`:
`b8f463f5c35fa62befcfed171a7a8a0886af20f7`.

- `tg_premium_emojis.py`, blob `6329dcf72c0314523d3616a01ca464829fbb320c`:
  `_SubstitutionOp`, `_apply_substitution_ops`, `apply_daily_free_premium_emojis`;
  surrogate-aware text edits, entity shifting, configured singles/compositions
  and idempotent intent. The generic emission loop assumes two UTF-16 units per
  part; arbitrary new sets need variable alt lengths. Some overlapping entities
  are dropped with a warning: do not import that as a success policy.
- `tests/test_tg_premium_emojis.py`, blob
  `11cf9eeeeb647a1b750f825883cf9709fa5798b6`: existing regression cases preserve
  links/bold and correct wrong IDs/idempotence. Read, not rerun in this batch.
- `scripts/tg_premium_emoji_editor.py` and
  `.codex/skills/tg-premium-emojis-update/SKILL.md` describe the operational donor;
  no execution/session/environment use is authorized here.
- `docs/features/tg-premium-emojis-update/README.md`: four-part free label, singles,
  venue pair and historical delayed edit behavior. Port the transformation, NOT
  its 150-second delay/jitter, env fallbacks, latest-message lookup or credentials.

Concrete regression seeds (historical metadata, not current live availability):
`label.free` ordered IDs `5406749623865857008`, `5407072545276973461`,
`5406815783542085177`, `5406927577245833438`; donor fallback `🆓🆓🆓🆓`.
Tretyakov pair: `5188445640325099838`, `5188470637034758005` from
`https://t.me/addemoji/lovekenigofficial`. The small thumbnail
`5188683852096234620` repeated twice is NOT that composite. Other donor examples
include theatre/pointing/rock and the `MostVKenig` set; import as opt-in candidate
palettes only after metadata/visual validation, not all-tenant defaults.

Read incidents:
`docs/reports/incidents/INC-2026-06-29-tg-premium-tretyakov-composite-pair.md`
records an actual two-small-buildings error because tests checked count instead
of the intended exact pair; contact-sheet validation caught it.
`docs/reports/incidents/INC-2026-07-05-tg-afisha-edit-spacing-premium-medallions.md`
records delayed enrichment and July 15 supersession: event medallions moved to a
graphical RichMessage strip. Do not resurrect that historical medallion pipeline
or confuse arbitrary custom-emoji sequences with event-medallion requirements.

## MCP delta (proposal, NOT implemented tool calls)

Keep eight canonical methods. Extend typed `vibepublish_destinations` actions for
palette registration/rule CAS, `vibepublish_read` for scoped catalog/preview, and
existing publish/update inline emoji aliases for use. Keep the exact grammar in
`contracts/social_mcp_v1.py`; select final action names there before implementation.
Add an emoji section to get_started/skill and update scoped catalogs. Do not
create per-pack/per-emoji synonym tools or use VisualService/imagegen to fabricate
emoji previews. Endpoint examples are not currently executable support.

## Acceptance package to implement

E01 set URL/type/metadata and limited access; E02 actual numbered previews and
stale-catalog selection rejection; E03 same-fallback/different-ID ambiguity;
E04 exact Tretyakov pair and four-part free label, order/repetition unchanged;
E05 UTF-16 variable-length alt/ZWJ/VS/modifier/flag boundaries;
E06 links/bold/italic/spoiler preservation and code/URL exclusion;
E07 idempotent compilation and deterministic overlapping-rule rejection;
E08 palette CAS, immutable approved expansion and revoked preview/cursors;
E09 precise native calls/readback now AND scheduled with zero post-edit timer;
E10 lost response/restart: reconcile semantic entities, no blind resend;
E11 multi-target explicit fallback and native-forward preservation;
E12 real MCP ClientSession/scoped catalogs and rendered desktop/mobile previews.

Source tests alone are not browser/live emoji evidence. Use scripted provider
fixtures then actual Telethon SDK serialization tests; live channel writes need
separate authorization and dedicated VibePublish credentials. Do not run the old
EventsBot editor to “prove” VibePublish works.

Primary Telegram references checked 2026-09-05:
https://core.telegram.org/api/custom-emoji
https://core.telegram.org/constructor/messageEntityCustomEmoji
https://core.telegram.org/bots/api#formatting-options
The first specifies exact alt wrapping and appConfig message_animated_emoji_max;
the Bot API documents separate bot eligibility. Check current official rules
again when enabling a specific connection. This design does not promise every
account can send every custom emoji in every channel.
