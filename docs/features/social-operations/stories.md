# Stories: VK and Telegram

Status: `Fixed` requirements from the owner (2026-10-28). Implementation status is per item below.

Owner wording (2026-10-28): «В сторис может быть выставлена картинка, а может быть выставлено видео, и в Телеграм, и в ВК». «В сторис нужно, чтобы срабатывал сценарий со ссылкой». «Для Телеграма желательно, чтобы то же самое могло быть: и ссылка на сайт, и ссылка на ВК, и другая ссылка».

## Requirements

| # | Requirement | Status |
| --- | --- | --- |
| S1 | VK story with **one image** or **one video** to a bound VK community. | `Done` for image and video (adapter `vk.py` `_execute_story`); live re-check `Not confirmed by user` after the 2026-10-28 reliability release. |
| S2 | VK story with a **link sticker to a VK wall post** of a bound community (e.g. `https://vk.ru/wall-241261191_193`, `vk.com` or `vk.ru`), button text `read`/`more`. The agent passes `story_link.item_ref` = post URL or item ref. | `Done` in code (`service._story_link`, `vk.py` `_story_link`); real owner scenario (dot → VK story linking post 193) `Not confirmed by user`. |
| S3 | VK story link to an **external website**. | `Not done`. Only own-community wall links are accepted today (`vk_story_wall_link_required`). Check VK API rules for community story links before implementing. |
| S4 | Telegram channel story with **one image** or **one video**, optional caption. | `Not done` — in progress (W5, branch `chatgpt/vp-reliability-w5-telegram-story`). |
| S5 | Telegram story with a **clickable link**: to a website, to a VK post, or any other HTTPS URL (Telegram URL media area / link sticker). | `Not done` — required in W5. Telegram may restrict link areas for channels by boost level; when not allowed, return a clear refusal, not an unknown state. |
| S6 | Stories are immediate (no native scheduling). A story request with a scheduled time is refused clearly before any effect. | VK: `Done`. Telegram: `Not done` (W5). |
| S7 | Same reliability contract as posts (audit §18.1): one operation, finite outcome (link or clear refusal), no manual review, networks independent, story delete supported for cleanup. | VK: `Done` via common worker (2026-10-28 release). Telegram: `Not done` (W5). |

## Agent recipe

Story = `vibepublish_publish` with the destination's `surface: "story"`, one `media` item (image or `video/mp4`), delivery now. Optional link: `story_link: {item_ref: "<VK post URL or item ref>", text: "read"|"more"}` (VK). Telegram link form is defined by W5 and must accept any HTTPS URL.

Related: [VK linked story dependency](vk-linked-story-dependency.md) (story created automatically after a new VK post), [native video publication](native-video-publication.md).
