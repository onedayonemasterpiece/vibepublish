# Native forwarding, editorial destinations and skill delivery

Date: 2026-09-04. Baseline: `7d55d4718c74720bde411b2838b7d59272fd8816`. Contract version: `1.2.0-design`.
Owner requirements: `Fixed`; engineering choices: `Not confirmed by user`; runtime: `Not done`.
This is the canonical extension of [Social Operations](README.md) and [MCP grammar](mcp-contract-v1.md). Native-only queues, progressive receipts and partner-bound reads from v1.1 remain unchanged.

## Delta

Already present: forward by internal item_ref, destination aliases/sets, get_started/skill, native scheduling and progress. Missing: exact source URL forwarding, source-access boundary, attribution readback, useful primary-channel descriptions, scoped profile editing and concrete implementation/test handoffs. This extension fills those gaps without adding another top-level tool.

## 1. Forward means native forward, not another authored publication

`vibepublish_engage` with `command.kind=forward` accepts `item_ref` as an authorized opaque item reference or an HTTPS Telegram/VK post permalink. It accepts explicit `to` aliases/sets, optional `delivery` (now or provider-native at), `selection` (post by default; message for one Telegram message) and `mode` (execute or preview). One call resolves the source internally and executes the requested native operation. There is no prerequisite model-visible resolve/read/copy/publish choreography.

```json
{"command":{"kind":"forward","item_ref":"https://t.me/venue/123","to":["announcements_tg"]}}
```

```json
{"command":{"kind":"forward","item_ref":"https://vk.ru/wall-123_456","to":["announcements_vk"]}}
```

These URLs and aliases are fixtures, not configured real destinations.

Telegram -> Telegram uses native forwarding preserving available provider origin/author information. VK -> VK uses a native wall repost preserving its source relationship. Do not rewrite text, download and re-upload media as a replacement, strip origin, add an editorial introduction, or substitute a plain link post. No `copy_if_forbidden`, `drop_author`, `rewrite` or raw SDK escape hatch is exposed. Cross-provider forwarding is not native forwarding: reject a mixed/cross-provider destination plan before any send, show the incompatible targets and let the user explicitly choose another operation. Never silently drop targets from a set.

The first VK scope is wall-post-to-wall/community repost. VK messenger forwarding, stories, videos not represented as a wall post and exotic provider objects require separate proven capabilities, not guessed analogues. MAX forwarding is not claimed by this extension; the first MAX task covers publishing and native queues.

### Source resolution and access

Parse only allowlisted native post URL forms, including supported t.me public/private post links and vk.com/vk.ru wall permalinks. Normalize tracking/query aliases deterministically, preserve the exact message/post selector and reject arbitrary redirectors, login URLs, embedded credentials, a channel home page without an item, a comment mistaken for a post and unsupported link forms. Do not navigate to arbitrary user-supplied URLs in an authenticated browser or fetch a broad channel feed to identify one link.

Partner forwarding may inspect the exact public post the user supplied even when its channel is not a publishing destination. This is an operation-scoped source-import permission, not a general read/search grant. Return only the requested source/album and operation evidence, not neighboring posts or account dialogs. Ordinary `read` remains restricted to publishing destinations.

Private sources require both actual provider access and caller authority to that source: a bound readable channel, a trusted tenant-owned incoming item, or an explicitly granted item-level share. Merely supplying a private URL which the operator's account happens to see is insufficient. Successful fetch is not proof of public visibility. Do not auto-join a private group or use another tenant's connection to satisfy the request.

If the user supplies a message previously forwarded to an authorized inbox, use its trusted exact item_ref and available provider origin metadata. Do not reconstruct an unavailable original from a display name or guess a missing message ID. With hidden origin, preserve what the provider actually exposes; do not fabricate original authorship. Forward restrictions/protected content are respected, with no download/screenshot/re-upload workaround.

`selection=post` expands a Telegram album only through a verified common grouped identity from the selected source. Preserve ordering and record every source/destination item mapping. No unrelated neighbor is included. `selection=message` forwards just the selected message. VK wall repost carries the entire native wall post; unsupported partial selection is rejected.

### Timing, integrity and lifecycle

Preflight source accessibility/forwardability, target publishing rights, supported surface and native scheduling capability for all targets. Then execute independent children with resolving_source, checking_forward_rights, submitting, reading_back and verifying events. Persist stable attempt identities before side effects; uncertain native forwards/reposts are reconciled, not repeated.

Store requested URL, normalized source identity, available origin chain, source snapshot/fingerprint, source-to-target item mapping, native queue/published identities, timestamps and operation actor in the existing publication history. `publication_kind=forward` is searchable; statistics target the resulting forwarded/reposted item, not the organizer's original unless explicitly requested and authorized.

Readback verifies target identity and native origin/source relationship as well as content/media grouping. A visually similar newly authored post is not success. `forward_origin` reports source_ref, provider, mode=native and origin_check (pending/matched/incomplete). Missing attribution proof stays incomplete and never triggers an automatic repost.

Source changes before submission invalidate a reviewed fingerprint; report external_change rather than silently forward a different revision. Source changes/deletion after posting are recorded as later observations; do not promise provider-independent immutability of repost presentation. Edits to a native forward's original body/media are unsupported unless the exact provider capability permits them; never convert it to authored content. Cancel/reschedule/delete affect the destination queue/item, never the source.

Telegram's documented messages.forwardMessages supports schedule_date and reports protected-chat/permission errors. The reviewed VK wall.repost schema supports target group_id and a user token, but does not include publish_date. Therefore VK immediate native repost is an implementation target; scheduled native repost stays needs_review/unsupported until a genuine native path is proved. Ordinary scheduled VK posts do not prove scheduled VK reposts. Never implement a timer or immediate repost as fallback.

## 2. Primary channels and editorial profiles

Keep existing native destination identity, binding and alias. Add a local per-principal editorial profile for each accessible destination or set:

- usage: primary or secondary (default secondary);
- purpose: what belongs here;
- audience, topics, avoid_topics;
- notes: free editorial comments;
- selection: explicit_only (default) or agent_may_choose.

`vibepublish_destinations(command.kind=profile_update)` updates these fields with profile `expected_revision` (0 creates the personal profile; otherwise exact current profile_revision). At least one field is required. Omitted fields stay unchanged; empty notes/topics clear those fields. The alias must already be bound/visible to the principal. This operation neither changes the provider channel nor grants access. Personal notes cannot overwrite another user's profile; owner-supplied presets may initialize personal profiles but are not a cross-tenant write channel.

```json
{"command":{"kind":"profile_update","alias":"announcements_tg","expected_revision":0,"profile":{"usage":"primary","purpose":"Анонсы концертов, спектаклей и выставок в регионе","topics":["концерты","театр","выставки"],"avoid_topics":["личная переписка"],"notes":"Короткие анонсы; сохранять источник при пересылке","selection":"agent_may_choose"}}}
```

Bootstrap returns authorized primary profiles first, then bounded pagination of secondary ones, with actual provider/capability identity, profile_revision and routing_revision. Purpose/notes are data for editorial routing, never executable security instructions.

When the user explicitly asks to publish/forward but omits a destination, the model may select a uniquely suitable permitted `agent_may_choose` destination/set from its saved profile, considering purpose, exclusions, provider and surface. It still passes explicit aliases in `to`. Echo `routing_revision` when selection used saved context; stale revisions produce refresh before any mutation. Explicit user choice takes precedence. Several equally plausible destinations, no match, explicit_only profiles, or incompatible provider/surface require one clarification or preview; never fan out to every primary channel as a guess. This is remembered routing for an authorized task, not autonomous background posting.

Narrow `forward` and `destination.profile` scopes can expose only engage.forward and destinations.list/profile_update for an active publisher. They do not expose replies/reactions, account-wide search or set administration by accident. Handler checks remain authoritative even for direct calls to hidden variants.

## 3. Ready-to-use skill is already a separate method

Keep `vibepublish_get_started`; do not add a synonymous ninth skill tool. It returns the actual versioned text, hash, schema version, token estimate, usable aliases/profiles/capabilities and examples, not just a URL to instructions. Extend section with forwarding, destinations and all. The same canonical skill is available as MCP resource/prompt where supported; a host may not automatically expose resources to the model, so the tool fallback remains required.

Static skill and dynamic personal routing data are separate inputs with separate invalidation: skill/schema version for instructions; policy epoch, routing_revision and capability observations for user context. `if_version` must not omit revoked bindings or stale profiles. No secrets or provider-controlled text may replace the trusted skill. An uninitialized client can call get_started immediately; tool descriptions must remain sufficient to identify that entrypoint.

## References and evidence boundary

Checked on 2026-09-04; documentation/schema evidence is not a live capability canary:

- Telegram: https://core.telegram.org/method/messages.forwardMessages
- Telegram Bot API differences/grouping: https://core.telegram.org/bots/api#forwardmessages
- VK official API schema 5.199 at 333481bd082ad747d4873ef4a77f9247097eeef0: https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/wall/methods.json (wall.repost).
- MCP resource handling is host/application controlled: https://modelcontextprotocol.io/specification/2025-11-25/server/resources

Implementation gates: [acceptance tests](acceptance-tests-v1.md). Work entrypoints: [core implementation](../../handoffs/implementation-start-20260904.md) and [MAX Web task](../../handoffs/max-web-codex-20260904.md).
