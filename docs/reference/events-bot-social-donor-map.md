# EventsBot social implementation donor map

Status: `Fixed`

Reviewed source: `onedayonemasterpiece/events-bot-new/main` on `2026-09-04`.

Purpose: identify the implementation, tests and operational lessons to port into
VibePublish Social Operations. This is an extraction map, not permission for a
permanent runtime dependency on EventsBot.

## Extraction rule

- Port the reusable provider-neutral and provider adapter behavior into
  `vibepublish` with provenance and focused regression coverage.
- Rename all deployment/session configuration into the VibePublish namespace.
- Preserve idempotency, durable receipts, readback, cooldown/fencing and secret
  boundaries.
- Remove EventsBot-specific product feature suppression and event-domain coupling.
- Do not expose arbitrary raw Telethon or VK provider-method passthrough.
- After parity, migrate EventsBot to the VibePublish service API and retire the
  duplicate social execution backend there.

## Provider-neutral core donors

| Source | Extracted responsibility |
|---|---|
| `private_events_mcp/social_workspace.py` | Platforms, targets, item kinds, reads, actions, rich entities, content/media model, granular scopes, validation, action digests and status schemas |
| `private_events_mcp/social_workspace_runtime.py` | Durable preparations/operations, encrypted opaque references, idempotency, retry/reconciliation, budgets, provider deadlines, asset ownership and audit |
| `private_events_mcp/social_workspace_tools.py` | Existing discovery/read/content/story/analytics/asset/action tools and output projections |
| `private_events_mcp_workspace_providers.py` | Durable provider bindings, encrypted native references, cross-process provider state, operation claims, leases and cooldowns |
| `private_events_mcp/media_contract.py` and media store/ingress modules | Verified immutable asset ingestion, hashes, ownership binding, MIME/geometry checks and bounded previews |

### Existing neutral operation inventory

Reads:

```text
resolve_target | resolve_item | search_targets | list_dialogs
list_items | search_items | get_item
list_comments | list_reactions | list_stories
get_statistics | get_audience | list_notifications
editorial_sample | list_scheduled_items
```

Mutations:

```text
send_message | publish | edit | delete | forward
reaction | comment | schedule | story
```

VibePublish extends this inventory with first-class destination sets,
rescheduling/cancellation, multi-provider parent operations, one-call high-level
publishing and MAX.

## Telegram donors

### Implementation

- `private_events_mcp_telegram_adapter.py`
- `private_events_mcp_provider_adapters.py`
- Telegram portions of `private_events_mcp_workspace_providers.py`

### Capabilities to preserve

- Saved Messages/self, exact user, group and channel resolution;
- dialog and target search, history/feed, exact item, comments/replies,
  reactions, stories, recommendations, audience/statistics and editorial sample;
- direct messages, Saved Messages, channel/group publication, comments/replies,
  edit, delete, forward, reactions, native scheduling and stories;
- rich entities including named links, mentions, custom emoji, spoilers, code,
  preformatted text and blockquotes;
- image, video and document staging/sending, ordered media and provider rights
  preflight;
- scheduled-history readback and scheduled deletion;
- Telethon FloodWait handling, persistent cooldown, lease/fencing,
  read-after-write verification and durable uncertain-outcome reconciliation.

### Configuration migration

The EventsBot session name `TELEGRAM_AUTH_BUNDLE_EVENTS_BOT_MCP` is a donor-only
reference. VibePublish uses its own session:

```text
VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE
```

No fallback to EventsBot, E2E or unrelated sessions is allowed.

### Regression sources

- `tests/test_private_events_mcp_telegram_workspace.py`
- `tests/test_private_events_mcp_telegram_media_stories.py`
- Telegram cases in social workspace runtime/server/config tests
- `.codex/lanes/mcp-universal-social-telegram/RESULTS.md`
- `.codex/skills/telegram-business-stories/SKILL.md`
- `docs/features/telegram-business-stories/`
- `docs/features/kenigsberg-stories/`
- `kaggle/CrumpleVideo/story_publish.py`

The Business Stories Bot API path is a separate optional connection type from the
owner Telethon session. Preserve both capability families without conflating
credentials or story identities.

## VK donors

### Implementation

- `private_events_mcp_vk_adapter.py`
- `private_events_mcp_vk_transport.py`
- `private_events_mcp_vk_upload.py`
- VK portions of `private_events_mcp_workspace_providers.py`

### Capabilities to preserve

- exact self, user and community resolution;
- wall, newsfeed/community search, dialogs/conversations, exact item, comments,
  reactions, stories, notifications, audience, post/story/community statistics,
  related-community discovery and editorial sampling;
- user direct messages, wall publishing and scheduling, comments/reactions,
  edit/delete, repost/forward analogue, photo albums, video and stories;
- photo/video/story upload-server flows with saved-provider readback;
- role-scoped actor selection and capability intersection;
- fixed provider call compiler/allowlist, idempotency claims, captcha cooldown,
  transport error classification and `outcome_unknown` reconciliation.

### Regression sources

- `tests/test_private_events_mcp_vk_workspace.py`
- `tests/test_private_events_mcp_vk_media_stories.py`
- `tests/test_private_events_mcp_workspace_providers.py`
- `.codex/lanes/mcp-universal-social-vk/RESULTS.md`
- `.codex/lanes/vk_media_stories/RESULTS.md`
- `.codex/skills/vk-community-video-publish/SKILL.md`
- `docs/features/vk-publishing/`
- `docs/features/promo-campaigns/`
- `promo.py`
- `kaggle/CrumpleVideo/story_publish.py`

## Story and rich-media donors outside the narrow MCP projection

The existing public Social Workspace projection does not expose every capability
already present in adapters and production workflows. In particular, its feature
switches and asset schema can reduce media ingress to images or Telegram-only
documents even when provider code supports video, native stories and other
roles.

VibePublish must inspect and preserve the broader working paths in:

- Telegram native Telethon stories;
- Telegram Business `postStory` fan-out;
- VK photo and video story upload/save;
- VK community video upload plus wall/story publication;
- CherryFlash/Kenigsberg multi-target story fan-out and its incident history;
- ordered media, album, scheduled-publication and readback tests.

Capability exposure in VibePublish is therefore per connection/target/surface,
not controlled by one global `media_story` or `private_read` product switch.

## Current EventsBot MCP tool donors

```text
social_capabilities
social_target_resolve
social_item_resolve
social_targets_search
social_targets_list
social_dialogs_list
social_content_search
social_content_feed
social_scheduled_items_list
social_content_item
social_content_thread
social_comment_hints_list
social_content_stories
social_content_editorial_sample
social_content_analytics
social_asset_stage
social_asset_status
social_asset_preview
social_action_prepare
social_action_commit
social_action_status
social_action_retry
```

These names are implementation evidence, not the final VibePublish model-facing
surface. VibePublish wraps them into the compact contract defined in
`docs/features/social-operations/README.md`.

## Gaps VibePublish must close

1. Add MAX as a first-class provider with deterministic Playwright execution and
   bounded Gemini Lite recovery.
2. Give VibePublish independent Telegram/VK credentials and provider bindings.
3. Add owner-wide read policy and tenant-bound external policy.
4. Add cross-provider `destination_set` management.
5. Add canonical semantic content plus explicit Telegram/VK/MAX renderings.
6. Expose photo/video stories and all verified media roles rather than an image-
   only public projection.
7. Add explicit scheduled reschedule/cancel operations.
8. Replace model-visible prepare/commit choreography with one-call high-level
   actions while retaining durable internal phases.
9. Add a versioned MCP skill/resource and compatibility skill tool.
10. Add parent/child fan-out receipts and resumable cross-provider batches.

## Live acceptance boundary

Source tests and historical receipts are donor evidence only. VibePublish does
not claim a capability live until its independently configured DevCoveer adapter
passes a provider-backed canary with exact remote readback. Donor production
credentials must never be copied into repository content or test artifacts.
