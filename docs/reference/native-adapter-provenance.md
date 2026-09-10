# Native Telegram/VK adapter provenance

> **Provenance record of the native-adapter checkpoint.** The donor reads and
> limitations below are historical, not a fresh live-provider audit. The later
> emoji and real-SDK work is documented in the [emoji workflow](../features/social-operations/telegram-custom-emoji-v1.md)
> and [SDK verification](../operations/dependency-sdk-verification.md). Current
> remote delivery still lacks three production modules; see [runtime status](../operations/social-runtime.md).

Status: **Not confirmed by user**. Implemented independently; EventsBot is not a
runtime dependency and no EventsBot credentials, sessions, imports or database
were used. Tests are scripted provider transports, not live capability canaries.

Historical donor read: `onedayonemasterpiece/events-bot-new` main at
`b8f463f5c35fa62befcfed171a7a8a0886af20f7` (2026-09-05 continuation).

| Read donor | Reused behavior / independent implementation |
|---|---|
| `private_events_mcp_telegram_adapter.py` blob `57dbc5d3ed4b4a6e231bba03b25e42834327c3a6` | Raw GetScheduledHistoryRequest; separate scheduled namespace; grouped_id logical albums ordered by native member ID; exact peer, text, UTC time and media binding; verified upload bytes; native attributed forward. Implemented in `adapters/telegram.py`. |
| `tests/test_private_events_mcp_telegram_workspace.py` blob `90cb18d18c8607de017c552c6d21e51fad9ff07a` | ParticipantPermissions uses is_creator/post_messages/edit_messages/delete_messages, not invented send_messages/post_stories properties. Provider-shaped TL fixtures in `tests/providers/scripted.py`. |
| `private_events_mcp_vk_adapter.py` blob `65cd722a3ef4309726cd3bda82313b05a2d9627e` | Role-specific tokens; wall.post/from_group/guid/publish_date; postponed queue readback distinct from wall.getById; no scheduled wall.repost assumption. Implemented in `adapters/vk.py`. |
| `private_events_mcp_vk_upload.py` blob `1511944b7c0e52aab640c5bbb54470925ebc9133` | Ordered verified bytes through getWallUploadServer, fixed multipart photo, saveWallPhoto; safe metadata receipts, not upload credentials. |
| `private_events_mcp_vk_transport.py` blob `de60b30f2557e6c028a2dd92dd75de2632dc68e5` | HTTPS/443 allowlist, public DNS validation plus pinned resolution, no redirects/proxies/cookies, bounded wire and decoded JSON. Independent implementation in `adapters/vk_transport.py`. |
| `tests/test_private_events_mcp_vk_media_stories.py` blob `effc8316dc26169f39edffa7b0252a8284417f04` | Native upload/wall response shapes, photo identities, scheduled readback. Stories remain a gate, not an implied port. |

Additional primary references checked: Telegram methods `messages.sendMessage`,
`messages.sendMultiMedia`, `messages.forwardMessages`, `messages.editMessage`,
`messages.getHistory`, `messages.deleteScheduledMessages` and
`updateDeleteScheduledMessages` at core.telegram.org; Telethon stable documentation
for 1.44. VK version 5.199 is the donor-tested pin, not a claim of latest API.

Safety deltas beyond donor: source bytes and ordered native photo IDs are compared
exactly (a matching count is insufficient); a lost response without durable native
IDs is unknown, never guessed by text; schedule readback cannot downgrade to now;
Telegram cancel requires UpdateDeleteScheduledMessages without sent_messages and
an empty exact native queue read. Lost cancel acknowledgement stays unknown.
Existing forwarded chains, multi-caption albums and unsupported account/surface
combinations are explicitly gated rather than flattened.

## Supported offline paths and retained gates

Telegram MTProto user: channel/Saved Messages text and verified image publication,
native schedules, album mapping, queue/feed/item reads, single-item text/image edit
and reschedule, album cancel/delete, native original-message/post forward with
source protection/rights checks. MTProto bot: only separately inspected immediate
paths; no native schedule/queue. Bot API and Business are not aliases.

VK user-role bundles: community text/images now or native postponed; paginated
queue/feed/search/item; native edit/reschedule/cancel/delete; immediate wall repost.
VK group token is a separate restricted family: no inferred user-token media or
native-schedule capability. Reader/editor/media roles never silently substitute
for each other. Scheduled repost is unsupported.

Still gated: Telegram multi-member album edit/reschedule, multiple captions,
full rich/mention coverage, video/documents/stories, inherited forward chains,
Telegram broad discovery and search, private personal VK walls, analytics refresh,
provider media download, persistent flood/captcha cooldown/recovery controls and
live canaries. These remain product requirements. Schema acceptance alone does not
claim their runtime support.

At the original native-adapter checkpoint, Telethon was not installed and tests
used native-shaped fixtures. Later complete-source verification added actual
Telethon 1.44 binary roundtrips and adapter tests, as recorded in the SDK runbook.
Current partial-source core verification fails on the undelivered rich-text
module; live rights/capabilities remain unverified.
The HTTP VK transport is implemented and covered by parsing/URL/token-policy
checks, not exercised against VK servers. No live requests were made.

## Basic-chat creator publication correction — 2026-09-05

Status: implementation/offline verification **Not confirmed by user**; live
canary **Not done** in this lane. The former unconditional Telegram group mutation
gate rejected an active basic `Chat` owned by the
current non-bot MTProto user. This is an implementation limitation, not a fixed
product prohibition. The bounded correction permits only a new immediate `post`
publication to that exact basic chat; no existing-item mutation, native schedule,
forwarding, bot, non-creator, megagroup or migration-following capability is added.

Telegram's [chat constructor](https://core.telegram.org/constructor/chat) identifies
`creator` as the current user's ownership flag and exposes `deactivated` and
`migrated_to`. Migrated basic groups must send new messages to the supergroup,
so this adapter rejects those rather than silently retargeting the publication.
[Telegram migration contract](https://core.telegram.org/api/channel)

[Telethon 1.44 permissions](https://docs.telethon.dev/en/stable/modules/custom.html#telethon.tl.custom.participantpermissions.ParticipantPermissions)
state that the creator has all permissions; `post_messages` is specific to
broadcast channels and must not be inferred for basic groups. Existing transport,
verified-media, immutable request, before-effect and exact-peer readback contracts
are reused unchanged. Preflight is not a live send/readback claim.

New offline regressions in `tests/providers/test_basic_chat_creator.py` cover
text, single image and album exact basic-chat readback, read-only preflight, rights
revocation before uploads/effects, an actual Telethon `Chat` constructor, and the
retained negative capability gates. No live Telegram RPC was made in this lane.
