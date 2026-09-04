# VibePublish Social Operations

Status: `Fixed`

Implementation status: `Not done`

Owner decision date: `2026-09-04`

Source voice session: `voice-20260904-105420-34603838`

## Goal

VibePublish is the independent social-network operations service for Telegram,
VK and MAX. It runs on DevCoveer and exposes the same application services
through MCP for models/agent clients and through an ordinary service API for
EventsBot and deterministic callers.

```text
ChatGPT / LADENO / EventsBot / other clients
                     |
                 MCP or API
                     |
          VibePublish Social Operations
                     |
          Telegram | VK | MAX adapters
```

VibePublish owns its provider adapters, credentials/session bindings, target
registry, destination sets, content rendering, durable operations, scheduling,
readback and audit. EventsBot is a source-code and regression-test donor and later
a client; it is not a runtime dependency of VibePublish.

## Product principles

- `Fixed` Provide broad real provider capabilities rather than a lowest-common-
  denominator posting API.
- `Fixed` Give models a small number of high-level tools. Provider-specific
  method sequences remain internal and deterministic.
- `Fixed` One logical action may fan out to Telegram, VK and MAX and must return
  a separate durable result for every destination.
- `Fixed` A successful transport call is not sufficient: each mutation requires
  provider-backed readback or an explicit `outcome_unknown` state.
- `Fixed` Provider differences are represented explicitly through capabilities,
  semantic content and platform renderings; they are not erased.
- `Fixed` Existing EventsBot functionality is migrated as a donor baseline and
  must not be artificially disabled by global product feature flags.

## Runtime ownership and connections

### Telegram

VibePublish uses its own Telethon session and its own adapter. It must never
borrow the EventsBot MCP session. The owner will add a dedicated server secret
whose name has the VibePublish prefix; the canonical session variable is:

```text
VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE
```

Telegram API credentials and any auxiliary provider settings must likewise be
read only from the VibePublish deployment configuration or approved shared
secret references, never from EventsBot module state.

### VK

VibePublish owns a separate VK adapter and a VibePublish-prefixed credential
namespace. Preserve the role-scoped provider approach already proven in
EventsBot (readers, messenger, publisher/media/story roles) while allowing one
physical credential to satisfy several roles when its verified permissions do.
There is no runtime call into EventsBot.

### MAX

VibePublish owns a persistent account profile and a specialized Playwright flow
engine. Ordinary DOM re-rendering is recovered deterministically. Gemini Lite is
used only for bounded UI-state/element recovery when the MAX interface has
changed semantically; it cannot choose a different business operation or bypass
commit/readback guards.

### Current deployment

The first deployment is single-owner on DevCoveer and may bind the already
available server-side provider credentials and browser sessions through the new
VibePublish namespace. The data model and authorization boundary must still be
multi-tenant-ready from the first implementation.

## Access profiles

### Owner operator

- `Fixed` May resolve, list, search and read any channel, group, chat, dialog,
  user, story or item visible to the connected owner account/session.
- `Fixed` May execute all actions allowed by the actual provider account rights.
- `Fixed` Is not limited to a predeclared shortlist for reads.
- `Fixed` Still receives exact-target checks, idempotency, durable operation
  state and readback for writes.

“Unrestricted” means unrestricted inside the resources actually visible and
permitted to the connected provider account; it does not fabricate provider
access that the account does not possess.

### External tenant

- `Fixed` Can read and mutate only destinations/accounts explicitly connected,
  ownership-verified and bound to that tenant.
- `Fixed` Cannot enumerate or search another tenant's destinations, dialogs,
  content, assets, sessions or operation history.
- `Fixed` Each Telegram/VK credential and MAX browser profile is isolated by
  tenant and principal, encrypted at rest and independently revocable.
- `Fixed` Write rights are the intersection of the tenant grant, destination
  binding and current provider permissions.

## Connections, destinations and shortlists

VibePublish stores three distinct entities:

1. `connection` — one provider account/session and its current capabilities;
2. `destination` — one resolved channel, community, group, chat, user or saved-
   messages target;
3. `destination_set` — a named shortlist spanning any number of providers, for
   example “Основные анонсы” or “Сторис партнёров”.

Required operations:

- `Fixed` Connect, inspect, reauthorize and revoke an account connection.
- `Fixed` Resolve/search/list destinations according to the active access
  profile.
- `Fixed` Add, remove, rename and list destinations in a named shortlist using
  simple commands.
- `Fixed` Store stable aliases while revalidating native identity and rights
  before every mutation.
- `Fixed` Allow one high-level action to target one destination, several explicit
  destinations or a destination set.

## Content model and platform rendering

Do not flatten all platforms into plain text. A publication package contains:

- a canonical semantic document: blocks, paragraphs, links, emphasis, mentions,
  hashtags, emoji tokens, captions and alt text;
- ordered media assets and their intended roles;
- optional explicit renderings for `telegram`, `vk` and `max`;
- a surface and delivery policy;
- typed provider overrides where a capability has no cross-provider analogue.

Rendering rules:

- Telegram may use named links, rich entities, custom/premium emoji and native
  Telegram media/story options.
- VK may render links as explicit URLs/lines and use VK-native attachments,
  albums, videos and story options.
- MAX may use named links and ordinary emoji but must not receive Telegram-only
  custom emoji entities.
- A caller may provide all platform renderings after reading the VibePublish
  skill. Missing renderings may be produced by deterministic renderers or by a
  bounded Gemini Lite adaptation step when enabled.
- Deterministic validation, target selection, asset identity, scheduling,
  idempotency and result verification remain authoritative even when a model
  prepares or repairs text.

## Capability model

Capability discovery is per connection, destination and surface. A capability
is reported as `supported`, `unsupported`, `needs_auth`, `needs_review` or
`temporarily_unavailable`, with provider evidence and observation time. A global
feature switch must not hide working functionality merely because another
provider lacks it.

The initial contract must preserve and expose all compatible EventsBot donor
capabilities, including:

### Reading and discovery

- exact target and item resolution;
- target search/listing and owner dialog listing;
- chronological feed/history reads and bounded content search;
- exact message/post/comment/story reads with media metadata and downloadable or
  staged asset references;
- comments, replies and reaction summaries;
- stories and story statistics;
- scheduled publication queues;
- notifications and comment/mention hints where available;
- audience, post, story and community/channel statistics;
- bounded editorial sampling and provider recommendations where available.

### Writing and management

- direct messages and Saved Messages;
- channel/group/community posts and wall publications;
- rich text, links, mentions, custom emoji and provider-native formatting;
- single media, ordered multi-media/albums, images, video, audio, animation and
  documents wherever the provider supports the role;
- immediate publication, native/provider scheduling and durable service
  scheduling;
- scheduled-item listing, rescheduling and cancellation;
- edit, media replacement and delete;
- forward/repost;
- comments/replies and reactions;
- photo and video stories, including provider-native story options;
- provider capabilities added later through typed extensions without exposing a
  raw arbitrary provider-method escape hatch.

## High-level MCP and service API

The model-facing surface is compact. The first contract consists of:

```text
vibepublish_skill_get
social_connections_manage
social_destinations_manage
social_read
social_publish
social_publication_manage
social_engagement
social_analytics
social_operation_status
```

`social_publish` is the primary entry point. It accepts destination refs or a
named destination set, `surface`, `delivery`, semantic content, ordered assets,
optional platform renderings and typed platform overrides. Supported surfaces
include at least:

```text
channel_post | wall_post | direct_message | saved_message
album | video | story | short_video
```

The same application service is exposed through REST/HTTP for EventsBot and
other deterministic callers.

For clarity, clients may also receive convenience aliases such as
`social_story_publish`; these aliases invoke the same `social_publish` engine
with `surface=story` and do not create a second implementation.

A complete explicit user instruction may be executed in one MCP invocation.
Prepare, persistence, validation, provider attempt and readback remain internal
phases. Preview-only and separately confirmed flows remain available for clients
such as LADENO that require an approval screen.

## MCP skills

VibePublish publishes a versioned social-publishing skill as an MCP resource or
prompt and provides `vibepublish_skill_get` as a compatibility tool for clients
that cannot consume MCP resources directly.

The skill explains:

- how to choose destinations and destination sets;
- how Telegram, VK and MAX formatting differs;
- when to provide platform renderings versus canonical semantic content;
- how stories, video, albums, scheduling and media ordering work;
- how to interpret partial fan-out, `outcome_unknown`, readback and retry rules;
- examples of correct single-provider and multi-provider requests.

The skill is instructional. It cannot grant capabilities, reveal credentials or
weaken server-side authorization.

## Reliability contract

Every logical request creates one durable parent operation and one child
operation per destination.

Required invariants:

- `Fixed` Caller-supplied idempotency is bound to the complete target, content,
  media, surface and schedule digest.
- `Fixed` Exact replay returns the existing canonical receipt; conflicting reuse
  is rejected before any provider call.
- `Fixed` Media are verified by digest, count and order.
- `Fixed` Edits and reschedules use compare-and-set preconditions where a prior
  state is known.
- `Fixed` A provider timeout after a possible mutation becomes
  `outcome_unknown`; no blind retry is allowed.
- `Fixed` Reconciliation reads the provider and either proves success/failure or
  keeps the operation unresolved.
- `Fixed` A failed destination does not erase verified success on another
  destination.
- `Fixed` Long batches persist an item-level checkpoint and resume from the first
  incomplete transition.
- `Fixed` Every receipt identifies the provider, destination alias, surface,
  requested schedule, observed provider state, media verification and transport
  used without exposing credentials or native secret material.

## MAX adaptive execution boundary

The MAX adapter uses deterministic state machines and Playwright semantic
locators first. Known recovery handles DOM refresh, stale elements, closed menus,
virtualized lists and page reloads without a model call.

Gemini Lite may receive a sanitized DOM/accessibility snapshot and a cropped
screenshot for one atomic transition only. It returns a structured candidate;
the guarded executor validates the candidate and the expected postcondition.
Gemini cannot publish, delete, change the destination, change content, retry an
ambiguous mutation or handle authentication challenges on its own.

## EventsBot extraction boundary

The implementation must port and adapt the proven provider-neutral contracts,
Telegram/VK adapters, upload paths, stories, scheduling, durable operation
ledger, readback and regression tests identified in
`docs/reference/events-bot-social-donor-map.md`.

After parity is established, EventsBot must call VibePublish instead of retaining
a second independently evolving social execution backend. Event-specific content
and editorial workflows remain in EventsBot.

## Delivery sequence

1. `Not done` Materialize this contract and the donor inventory.
2. `Not done` Extract the provider-neutral core plus independent Telegram/VK
   adapters into VibePublish and bind VibePublish-prefixed server sessions.
3. `Not done` Build the deterministic MAX Playwright flow engine and regression
   corpus, then add bounded Gemini recovery.
4. `Not done` Expose the compact MCP/resource surface and matching service API.
5. `Not done` Run owner-profile live read/write/story/schedule canaries on
   DevCoveer with provider readback.
6. `Not done` Migrate EventsBot to the VibePublish service API.
7. `Not done` Add external-tenant onboarding, connection isolation, ownership
   verification, quotas and revocation.

## Acceptance

- VibePublish independently reads and operates Telegram, VK and MAX using its own
  connections.
- Owner reads are broad across everything visible to the connected accounts;
  external reads are tenant-bound.
- One call can publish a post or story to a cross-provider destination set and
  returns per-destination receipts.
- Telegram/VK/MAX renderings preserve platform-specific formatting rather than
  falling back silently to the weakest format.
- Photo/video stories, media publications, scheduling, rescheduling, editing,
  deletion and readback are available whenever the current provider connection
  advertises them.
- A DOM refresh or process restart does not lose a MAX batch checkpoint.
- `outcome_unknown`, duplicate prevention and partial fan-out are demonstrated by
  regression and live canary evidence.
- EventsBot contains no required runtime credential or provider execution path
  for VibePublish after migration.
