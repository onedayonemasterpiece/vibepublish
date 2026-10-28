# Telegram channel stories (W5)

Status: **Draft / Not confirmed by user**. Owner requested Telegram channel stories alongside VK stories on 2026-10-28. This is an implementation contract, **not** evidence of live Telegram permission or publication.

## User-facing contract

Use the existing `vibepublish_publish` command with a Telegram channel binding and `surface="story"`, exactly as for a VK story. A story has **one** image or **one** MP4 video (native verified asset) and optional caption from `content.text`. Stories with `scheduled_at`, forwards, linked VK wall-post dependencies, albums, topic roots, PDFs or multiple assets are **not supported**; reject before dispatch with an actionable reason. No new tool, table, queue, execution state or local scheduling.

The publishing identity is the **bound channel** (never the operator's personal account). Only MTProto user sessions with actual story-posting authorization are eligible. Before uploading/sending, `stories.canSendStory(peer=channel)` must succeed and report an available slot; Telegram may require channel boosts and `post_stories` admin rights. If boosts, permissions or available quota prevent posting, return `telegram_story_not_allowed` and a useful reason; do not attempt `stories.sendStory`. Unexpected transport errors keep the existing transient-error handling rather than masquerading as a known denial.

A successful send uses `stories.sendStory` with `privacy_rules=[InputPrivacyValueAllowAll()]`, caption and entities where supported, `period=86400` (24 hours) and the already-prepared one-photo/video `InputMedia`. Reuse the normal provider `prepare → execute → checkpoint → before_effect → observe` hooks, the existing worker lane, progress vocabulary, and error processing. The deterministic attempt `random_id` must be checkpointed **before** the effect. Recovery after a lost response may replay exactly the same RPC with the **same** `random_id`, relying on Telegram deduplication; it may read a known ID with `stories.getStoriesByID`. It must not search/identify a story from a matching caption, time or media.

## Native identity, readback and deletion

Extract the exact story ID from the provider's `UpdateStoryID` correlated to the submitted `random_id`; `stories.getStoriesByID(peer, id=[story_id])` establishes identity and media presence. A public channel with a verified username has `https://t.me/<handle>/s/<story-id>`; for private channels, return the native ID without inventing a public permalink. The result is a normal `RemoteItem(namespace="story")`, and independent Telegram/VK destinations finish independently. A story `publication_update` delete uses `stories.deleteStories(peer, id=[story_id])` followed by exact-ID absence verification, without replacing or re-creating an effect. Edits, reschedules and cancellations of Telegram stories are not implemented.

No new hashes/fingerprints are calculated to prove Telegram's own uploaded media. Do not create new storage fields or manual-resolution gates. Use only existing terminal workflow states and `emit_progress` stages `started/completed/failed/blocked/unknown`.

## Acceptance

Focused offline fake-Telethon tests: eligible photo/video, caption, boosts/permissions/quota refusals before send, scheduled/multiple-asset rejection, correlated UpdateStoryID, exact readback/link/media, delete, and lost-response replay with unchanged random_id. The supplied venv and focused pytest files only; **no live Telegram requests, production publication, deployment or release**. Live user approval remains unconfirmed after unit tests and PR review.

References: [MCP contract](mcp-contract-v1.md), [VK linked stories](vk-linked-story-dependency.md), [reliability decisions §18.1](../../reports/publish-reliability-audit-20261027.md).
