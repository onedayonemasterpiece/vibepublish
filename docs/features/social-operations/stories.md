# Stories: VK and Telegram

Status: `Fixed` requirements from the owner (2026-10-28). Implementation statuses are separate from live acceptance.

Owner wording (2026-10-28): «В сторис может быть выставлена картинка, а может быть выставлено видео, и в Телеграм, и в ВК». «В сторис нужно, чтобы срабатывал сценарий со ссылкой». «Для Телеграма желательно, чтобы то же самое могло быть: и ссылка на сайт, и ссылка на ВК, и другая ссылка».

## Requirements

| # | Requirement | Status |
| --- | --- | --- |
| S1 | VK story with **one image** or **one video** to a bound VK community. | `Done` for image and video (adapter `vk.py` `_execute_story`); live re-check `Not confirmed by user` after the 2026-10-28 reliability release. |
| S2 | VK story with a **link sticker to a VK wall post** of a bound community (e.g. `https://vk.ru/wall-241261191_193`, `vk.com` or `vk.ru`), button text `read`/`more`. The agent passes `story_link.item_ref` = post URL or item ref. | `Done` in code (`service._story_link`, `vk.py` `_story_link`); real owner scenario (dot → VK story linking post 193) `Not confirmed by user`. |
| S3 | VK story link to an **external website**. | `Not done`. Only own-community wall links are accepted today (`vk_story_wall_link_required`). Check VK API rules for community story links before implementing. |
| S4 | Telegram channel story with **one image** or **one video** (MP4), optional caption. | **Done in code / Not confirmed by user** (W5, `adapters/telegram.py`, offline mock tests; no live send). |
| S5 | Telegram story with a **clickable link**: to a website, to a VK post, or any other HTTPS URL (Telegram URL media area / link sticker). | **Done in code / Not confirmed by user** (W5 `MediaAreaUrl` send/readback and provider capability check; no live confirmation). |
| S6 | Stories are immediate (no native scheduling); scheduled requests are rejected before any provider effect. | VK: `Done`. Telegram: **Done in code / Not confirmed by user** (W5). |
| S7 | Same reliability contract as posts (audit §18.1): one operation, finite outcome (link or clear refusal), no manual review, networks independent, story delete supported for cleanup. | VK: `Done`. Telegram: **Done in code / Not confirmed by user** (W5 reuse of worker/checkpoints and exact ID). |

## Agent recipe (single MCP publication command)

Send `vibepublish_publish` with `surface:"story"`, one `media` item (image or MP4), `delivery` now, and an optional `content.text` caption.

- **VK**: `story_link: {"item_ref":"<bound VK wall-post URL or item ref>","text":"read"|"more"}`. VK external web links remain unsupported (S3).
- **Telegram**: `story_link: {"url":"https://example.org/page","text":"Подробнее"}`, or `{"url":"https://vk.com/wall-1_2"}`. Any absolute HTTPS URL is allowed; no separate binding to that external destination is required because it is only opened when the viewer clicks the sticker. `text` is optional editorial input. The MTProto `MediaAreaUrl` constructor carries **URL and coordinates only**; it has no customizable label field. VibePublish does not claim the label will render natively. `content.text` is the actual caption.

Do not schedule a story or retry `publish` after an accepted response; use the original operation ID with `vibepublish_status`. A mixed VK/Telegram story without a link can use one publication; a linked story uses its provider-specific `story_link` form.

## Telegram channel story execution and verification (W5)

Owner authorization / status: **Fixed requirements; Done in code / Not confirmed by user**. No production effect or live canary authorized by offline acceptance.

1. Use the current `mtproto_user` session and the **bound broadcast channel**, never the user's personal profile. Require Telegram's native `post_stories` right. The read-only `stories.canSendStory(peer)` API confirms channel boost authorization and remaining quota; when denied, return `telegram_story_not_allowed` with reason, **before upload or send**. For linked stories, also inspect `help.getAppConfig` `stories_area_url_max`; if it is unavailable or under 1, return `telegram_story_link_not_allowed` before upload or send. This is the Telegram-exposed link-area capability; there is no separate documented per-channel link-sticker boost threshold. Network errors use the existing worker transient policy, not a fabricated permission refusal.
2. Use the ordinary trusted asset pipeline for exactly one photo or one MP4 video. Build `stories.sendStory` with `privacy_rules=[InputPrivacyValueAllowAll()]`, optional caption/entities, `period=86400` (24 hours). For a link, send one `MediaAreaUrl(coordinates=MediaAreaCoordinates(x=50,y=80,w=70,h=10,rotation=0), url=...)`. Telegram has no native schedule on this surface; PDFs, text-only, multi-asset stories, forwards, story edits, topic roots and linked VK wall-post dependencies are not implemented.
3. Use existing `prepare → execute → checkpoint → before_effect → observe`, worker, stages and source-asset validation. The deterministic `random_id` is durably checkpointed **before** `stories.sendStory`; an interrupted response is recovered with the **same** RPC and random_id, never by searching nearby stories, captions, images, or times.
4. `UpdateStoryID` maps the returned `random_id` to the exact story ID. `stories.getStoriesByID(peer,id=[id])` verifies story ID, one media item, caption and, when requested, **the exact URL present in its `media_areas`**. Preserve native link observation in the existing `RemoteItem.story_link_json`; do not claim verification if the area is missing or differs. Public channel `https://t.me/<handle>/s/<id>` permalinks are returned only for a verified public handle; otherwise return the native item reference without inventing a public URL.
5. Delete is `publication_update` on that exact `story` item, via `stories.deleteStories` and exact-ID absence readback. All destinations finish independently in the existing worker; one blocked Telegram channel cannot cancel an accepted VK publication.

The shared Telegram rights path also serves older emoji-catalog and destination-discovery requests that do not carry a `surface` field. For those calls, absence of `surface` continues to mean ordinary `post`; explicit `story` still requires story-specific channel rights. The offline SDK wire gate covers all 21 adapter RPCs, including four Story operations.

No new tables, persisted flags, SHA gates, statuses, local schedule or separate retry system. The only verification performed for this PR is **offline**: real Telethon 1.44 request construction, scripted channel permissions/capacity, photo+video, HTTPS areas, exact-ID readback/deletion, lost-response replay, provider isolation, and rejection cases. Live Telegram behavior is **Not confirmed by user**.

Related: [VK linked story dependency](vk-linked-story-dependency.md), [MCP contract](mcp-contract-v1.md), [native video publication](native-video-publication.md), [reliability audit §18.1](../../reports/publish-reliability-audit-20261027.md).
