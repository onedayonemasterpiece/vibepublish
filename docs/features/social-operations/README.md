# VibePublish Social Operations

> Current remote delivery: **partial, not a runnable release**. The implemented
> behavior and historical test counts below describe the complete archived source.
> Three production modules remain undelivered; current evidence and exact boundaries
> are in [runtime status](../../operations/social-runtime.md).

Current bounded runtime contract/skill: **1.5.0-runtime**, eight tools unchanged.
[Telegram custom emoji](telegram-custom-emoji-v1.md) now has private catalogs,
numbered visual selection, frozen aliases/rules and semantic native entities.
This is offline implementation, **Not confirmed by user**, not a live Telegram
capability claim. Historical design versions below remain requirements context.

> Offline core and native adapter snapshot: [runtime runbook](../../operations/social-runtime.md).
> This is not complete provider implementation or deployment; canonical goals
> below remain binding, including all retained capability and live-verification gates.

Owner requirements: `Fixed`, including the follow-up correction of 2026-09-04.
Engineering realization: selected design `1.1.0-design`, `Not confirmed by user`.
Runtime implementation: core, native Telegram/VK subset and offline VisualService **Not confirmed by user**; remaining capabilities **Not done**.

Contract 1.3 adds mutually exclusive native `item_ref` lifecycle commands (scoped
remote-snapshot CAS) and read-ref forwarding; see the runtime runbook and
[native provenance](../../reference/native-adapter-provenance.md). Native item
management never grants access to another author's private draft or assets.

Contract 1.4 implements the existing visual method and inline branch through one
VisualService, selected-asset hashes, scoped binary resources and single parent
continuation. It does not add a ninth method. Real executor, initial-preset human
acceptance and live capabilities remain unverified; see [visuals](../social-visuals/README.md).

## Current source of truth

Read [implementation design](implementation-design-v1.md), [MCP contract](mcp-contract-v1.md), the executable `contracts/social_mcp_v1.py` and the [agent skill](../../llm/vibepublish-social-skill.md).

The [original audit](../../reports/vibepublish-audit-20260904.md) and [handoff](analysis-handoff-20260904.md) are historical evidence, not competing current instructions. In particular, the audit's service-scheduler decision and separate default-deny read-grant decision were rejected by the owner and are superseded here. Imagegen and MAX Web requirements remain binding.

## Owner correction: real provider queues, no local publication scheduler

`Fixed` A scheduled publication is submitted immediately to the native queue of Telegram, VK or MAX. The provider owns execution at the requested time. VibePublish must not maintain a timer, cron job, delayed-send worker or fallback that publishes at that time. This is not merely a change of default backend: local scheduled delivery is excluded.

`Fixed` The person scheduling can inspect the actual queued post at the provider, including its content, media and scheduled time. Success requires readback from that queue, not a local database row, composer screenshot or acceptance toast. The receipt contains an authorized queue/item reference and an actual provider link when available; otherwise it provides exact navigation instructions and protected observed preview evidence. Do not invent a permalink or promise provider-UI login access to a partner who only has VibePublish access.

`Fixed` Cancel, edit and reschedule operate on the existing provider item and verify the change there. A local flag alone is not cancellation. Native queue reads include all items visible in the authorized destination, including those created outside VibePublish.

A connection/surface whose native scheduling has not been proved is reported unsupported, needs authentication or needs review. Never substitute immediate sending or a local queue. MAX continues through its Web UI, not an API. Proving MAX native scheduling/readback/edit/cancel is an implementation gate, not an availability claim made by this design.

The worker may process accepted commands, imports, uploads and observations now. Its short-lived execution backlog is not a publication calendar. On-time provider submission, expired requests and uncertainty are explicit; no accepted command may later become a hidden local scheduled send.

## Owner correction: progressive visibility

`Fixed` The agent must receive accepted state and successive atomic stages without waiting for all providers to finish. Every meaningful operation transition and per-destination result is durably recorded and exposed immediately through incremental status results. Telegram completion must be observable while VK is uploading and MAX is still checking the channel.

The portable contract is a prompt initial receipt plus resumable event cursors through `vibepublish_status`. MCP progress notifications are an optional additional projection during an active request, never the sole visibility mechanism. No promise is made that every client displays or passes notifications to its model. Stage events survive disconnect/restart and never imply permission to retry an uncertain mutation.

An operation that successfully placed all requested items in provider queues is complete as a scheduling command. It does not remain running until publication time. Actual later publication is a separate provider observation.

## Owner correction: reading follows publishing destinations

`Fixed` A partner with active publication access to a bound channel can read all provider-visible content in that channel, including its entire scheduled queue, regardless of which editor or client created the posts. A separate social-read grant is not required for that channel.

The partner can read/search only such destinations, not arbitrary public channels, the operator's unrelated chats, dialogs or account-wide search. Exact links, IDs, cross-post links, media handles, cache entries and pagination cursors cannot expand this boundary. Comments/replies tied to an authorized post can be read where supported; this does not grant the whole linked discussion chat. Provider limitations still apply and are shown honestly.

`Fixed` The system owner may request any chat, channel, dialog or item actually visible to the connected provider account, without a predeclared publishing shortlist. This is bounded by real provider access, not an invented ability to read inaccessible resources.

Read access to shared channel content does not expose another tenant's private drafts, source assets, prompts, credentials, operation logs or generation candidates. The channel-visible projection is distinct from those private records. Revoking a binding invalidates access to cached channel content too.

## Owner correction: searchable publication history

`Fixed` Keep durable facts and references for operations and publications in the database: authorship/provenance, destination, provider item/queue identities, content/media fingerprints, requested and observed time, state and observations. This is an index/history and audit trail, not an execution scheduler.

The agent can find its earlier publications quickly using local history, then request cached statistics or refresh statistics for those exact provider items. Return observation time, provenance and freshness. A native queue read always contacts the provider; local history must not masquerade as its current contents. Missing remote items and queue-to-published ID changes are reconciled rather than guessed.

## Product and provider ownership

VibePublish is one independent service on DevCoveer with MCP and HTTP interfaces over the same application services. It owns adapters, connection references, tenant/principal bindings, aliases/sets, semantic rendering, assets, immediate command execution, native queue management, observations, history and audit.

Telegram uses independent VibePublish sessions, including the canonical `VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE`; never fall back to EventsBot/E2E sessions. Bot API/business connections remain separate capability families. VK uses independent role-scoped VibePublish credentials and reusable donor transport/upload/readback behavior. MAX uses an isolated persistent profile and specialized Playwright driver; no general-purpose model agent selects targets or clicks submit.

Tenant-owned credentials and operator-shared credentials are both supported. Operator-shared access requires an owner-created exact destination binding and actual provider publishing rights. Supplying a URL never creates a binding. Multi-tenant isolation, secure onboarding, quotas and revocation belong to the first core batch; the initial administration surface may be owner-only CLI.

EventsBot is a source/test donor and later an API client, never a required runtime dependency or parallel evolving social writer. Domain/editorial event rules remain there. The [donor map](../../reference/events-bot-social-donor-map.md) is inventory, not proof of live VibePublish capabilities.

## Content and full capability baseline

Preserve plain/semantic/rich content, ordered image/video/audio/animation/document media, explicit provider renderings, mentions/emoji, captions and alt text. No silent loss, splitting or lowest-common-denominator downgrade. Optional model adaptation creates a reviewable revision before dispatch; facts, targets and time are never rewritten during execution.

Preserve all verified donor-compatible capabilities: destination/item discovery, feeds/history/search, comments/reactions, stories/statistics, scheduled queues, notifications, audience/community analytics, editorial sampling, recommendations, direct/Saved Messages, posts, albums/video/stories, edits/media replacement/deletes and forwards/reposts. Expose native-specific options through typed fields and tests, never a raw SDK escape hatch. Capabilities are per connection/destination/surface with evidence and observation time.

## MCP surface

The eight task methods remain:

```text
vibepublish_get_started
vibepublish_publish
vibepublish_publication_update
vibepublish_visual
vibepublish_status
vibepublish_read
vibepublish_engage
vibepublish_destinations
```

An active partner publisher normally receives six core methods, including `read` restricted to publishing destinations. Owner-only discovery is not exposed in that partner projection. No separate story/schedule synonym and no model-visible prepare/commit choreography. One publication mutation creates one operation; progress reads do not create extra publications.

## Reliability and related features

Keep request identity separate from the immutable execution plan; freeze concrete set members, content, selected assets and schedule. Preserve per-provider successes. Perform deterministic all-target preflight while publishing its stages; after dispatch, providers proceed independently. Record the dispatch boundary before side effects. Unknown outcomes are reconciled, never blindly retried. Media evidence distinguishes input hashes from provider-transcoded results.

[Social visuals](../social-visuals/README.md) preserves `$imagegen` through the requested `gpt-5.6-luna` route, candidate choice, deterministic exact typography and separate training consent. A pending visual is not yet a queued provider post; approval/selection after the native lead-time window blocks submission instead of sending immediately.

[Video stories](../video-stories/README.md) preserves Telegram editorial control, Kaggle rendering, voice comments, geography/time filters, music, subtitles, safe enhancement and approval. Its output enters this same publishing service; it never adds a local social scheduler.

## Delivery status

This is a design/contract correction, not provider implementation or deployment. New schemas, fixtures and tests describe the corrected contract. Native scheduling, MAX UI, progressive behavior in actual MCP clients, scoped runtime reads, database/history/statistics and imagegen still require the implementation/live gates in the design. No Codex task or live provider operation is authorized or performed by this correction batch.
