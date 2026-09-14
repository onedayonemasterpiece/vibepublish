# VibePublish: handoff анализа Social MCP + `$imagegen`

Status: `Analysis handoff`

Implementation status: `Not done`

Date: `2026-09-04`

Repository: `onedayonemasterpiece/vibepublish`

Starting checkpoint: `71120741316e70d407592f08079caa568ad87e44`

This document is the authoritative continuation source for the next ChatGPT
window. It restores the relevant IdeaHub voice context, records the owner's latest
corrections, and defines the analysis/implementation boundary. It is not a claim
that the Social Operations runtime is already implemented.

## 1. Binding owner corrections

The following decisions override any contrary conclusions from the preceding
ChatGPT analysis.

### 1.1 MAX remains Playwright-based

There is currently no approved or practically connectable MAX API path for this
project. Do not redesign MAX as API-first and do not block the implementation on
MAX API agreement.

The first working MAX adapter must use a persistent authorized browser profile on
DevCoveer and a specialized Playwright state machine. It must provide guarded
publication, scheduling, editing/deletion where the UI supports them, exact target
selection, durable checkpoints and provider-visible readback.

A future MAX API adapter may be added later behind the same internal provider
contract, but it is outside the current implementation and must not distort the
MCP surface.

### 1.2 Image generation means the working `$imagegen` route

The intended image path is not a direct Google Imagen API client. The project has
already tested the image-generation capability available to Codex through a
`$imagegen`-style invocation, and it produced real image artifacts.

For this project the request must be executed through `gpt-5.6-luna`. The exact
runtime invocation, file-return contract and authentication available on
DevCoveer must be fresh-read and proved during implementation. Do not substitute
Google AI Studio Imagen/Gemini image APIs merely because the existing repository
contains `google_ai.GoogleAIClient`.

Use a provider abstraction such as `ImagegenExecutor`; its first implementation
is the tested Codex/DevCoveer `$imagegen` route using `gpt-5.6-luna`.

### 1.3 MCP methods must be designed from zero for weak agents

Do not copy the existing EventsBot Social Workspace tool catalog and do not treat
its current method names as the target API. EventsBot is a donor of provider code,
durable state, validation, readback and tests only.

The VibePublish MCP surface must be derived from real user jobs and optimized so
that a medium, weak or unsophisticated agent does not confuse:

- which method to call;
- which destination identifier to use;
- which fields belong to which operation;
- Telegram/VK/MAX formatting differences;
- media staging and ordering;
- scheduling versus immediate publication;
- preview, approval, retry and status semantics;
- image generation, tuning and candidate selection.

A normal complete publishing instruction should require one model-visible
mutation call. Internal prepare, persistence, upload, provider execution and
readback remain deterministic server phases.

### 1.4 Delivery split

Initial code implementation is performed directly in a ChatGPT window against
GitHub. Codex on DevCoveer is reserved for final environment integration, exact
`$imagegen` verification, real credentials/browser profiles, live canaries and
provider drift debugging.

Do not delegate the first implementation back to Codex.

## 2. Restored source context

Fresh-read the current heads before work. The following are the key source
packets and canonical documents found during reconstruction.

### IdeaHub voice packets

- `voice-20260829-074249-246c3114` — server-mediated social integrations for
  external users; Integration First; Telegram/VK already existed in EventsBot.
- `voice-20260830-233239-5e1db659` — on-demand comments monitoring and skill-led
  analysis; owner/partner rights differ.
- `voice-20260902-145903-5cf6991a` — end-to-end content pipeline, author social
  accounts, visual generation and cross-platform distribution.
- `voice-20260902-154844-651facb3` — optimize MCP processes; do not build a new
  parallel execution contour when proven logic already exists.
- `voice-20260902-163949-7ee6120d` — lifecycle publication on event
  cancellation/rescheduling.
- `voice-20260902-164447-cabb5893` — derived visual status badges without
  mutating original media.
- `voice-20260902-173441-d86517ba` — owner-only partner lifecycle, roles,
  capabilities, credentials, suspension and MCP-only access.
- `voice-20260902-191109-49718fed` — local-to-DevCoveer agent task bridge for
  end-to-end debugging.
- `voice-20260903-081830-f0c7e4f5` — social publication/browser automation and
  future cross-channel media capabilities.
- `voice-20260904-105420-34603838` — VibePublish as independent Telegram/VK/MAX
  service; destination sets; compact methods; versioned MCP skill; reliable
  readback.
- `voice-20260904-134324-87da0103` — generated weather stories and reuse in
  video workflows.
- `voice-20260904-165005-c0a0bcbe` — image tuning/generation from rough PIL-like
  drafts, optional automatic processing, multiple candidates and selection.
- `voice-20260904-171603-ff37739b` — external-user service model, keys/quotas and
  managed integrations.
- `voice-20260904-173825-abdc1111` — multi-channel distribution across Telegram,
  VK and MAX for public and restricted content streams.

### Canonical repository documents

- `docs/features/social-operations/README.md`
- `docs/reference/events-bot-social-donor-map.md`
- `docs/features/llm-gateway/README.md`
- `docs/routes.yml`
- IdeaHub:
  `ideas/product.vibepublish/idea-20260903-social-publishing-audio-and-browser-automation.md`

The Social Operations requirement is fixed but the runtime is explicitly marked
`Not done`. The existing `google_ai` package is implemented, but it is not the
requested `$imagegen` executor.

## 3. Product boundary

VibePublish is one independent service on DevCoveer with two projections over the
same application services:

```text
ChatGPT / LADENO / EventsBot / other agents
                 | MCP or HTTP API
                 v
             VibePublish
                 |
      Telegram | VK | MAX/Playwright
                 |
        optional `$imagegen`
```

VibePublish owns:

- provider connections and encrypted credentials/session references;
- principals, tenants, grants and destination bindings;
- stable destination aliases and named cross-platform destination sets;
- semantic publication content and provider renderings;
- immutable source assets and derived assets;
- visual generation/tuning jobs and accepted candidates;
- scheduling and publication lifecycle;
- idempotency, leases, retries, reconciliation and receipts;
- MCP resources/prompts/tools and the ordinary service API.

EventsBot remains a donor and later becomes an API client. Event-domain rules stay
in EventsBot; social-provider execution must not remain as a second independently
evolving backend after migration.

## 4. Required providers and connection modes

### Telegram

Support separate VibePublish connections. Preserve the proven Telethon owner
session path, Bot API/business paths where useful, rich entities, media, albums,
scheduling, edit/delete, comments/reactions and stories when the particular
connection advertises them.

Canonical owner session environment namespace:

```text
VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE
```

### VK

Port the proven role-scoped token, transport and upload logic from EventsBot.
Capabilities remain per connection/destination/surface, including media, albums,
video, stories, scheduling, edit/delete, comments/reactions and analytics when
proved by the bound credential.

### MAX

Use one or more persistent Playwright browser profiles on DevCoveer. Start with a
deterministic driver:

```text
intent
-> durable operation
-> exact destination resolution
-> semantic Playwright locators
-> deterministic recovery
-> guarded mutation
-> UI/provider readback
-> receipt
```

Handle DOM refresh, stale handles, virtualized lists, closed dialogs and process
restart without blindly repeating a possible mutation. Model-assisted UI recovery
may be considered only as a bounded repair mechanism after deterministic flows
exist; it must not be allowed to change target, content, schedule or retry an
ambiguous mutation.

## 5. External users and access model

Two connection patterns are required.

### Tenant-owned credentials

A user supplies their own Telegram/VK/MAX credential or session through an
approved secure onboarding path. Credentials are encrypted, independently
revocable and isolated by tenant/principal.

### Operator-shared credentials

The owner's provider account/bot/browser profile may publish to a destination
only when that account has real administrator/publisher rights and an owner-created
binding grants the external principal access to that exact destination.

An external user must never gain access by merely supplying another channel URL,
name or native provider ID.

### Initial administration

A complete access-management UI may be postponed. The first release may create
principals, tokens, connections, bindings and grants through an owner-only CLI or
Codex-assisted server operation. The underlying multi-tenant boundaries, audit
and revocation must exist from the first release.

### Read policy

- Owner: may read/search everything visible to the connected owner sessions,
  subject to actual provider rights.
- External user: no social reading by default.
- Selected external users: may receive explicit read grants for specified
  destinations and operation classes.
- All provider content is untrusted external data and cannot act as instructions
  to expand access or perform mutations.

## 6. MCP design mandate

The next window must design the MCP contract from real task grammar before
implementing tools.

### 6.1 Build a task corpus first

Create at least 40 natural-language jobs covering:

- publish one Telegram/VK/MAX post;
- fan-out to a named destination set;
- immediate and scheduled publication;
- one image, ordered multi-image album, video and story;
- generated image, tuned image and composition from sources;
- candidate preview/selection;
- edit, reschedule, cancel and delete;
- comments/reactions where allowed;
- status after timeout or process restart;
- owner reads and restricted external reads;
- own credentials and operator-shared credentials;
- partial cross-provider success;
- duplicate request and conflicting idempotency reuse;
- unsupported provider capability and reauthorization.

Use these jobs to derive the smallest non-overlapping set of tools.

### 6.2 Tool-design rules

- One user job maps to one obvious top-level method.
- Tool names use product tasks, not provider SDK verbs.
- Do not expose asset-stage/prepare/commit choreography to the model.
- Do not expose raw Telethon/VK/Playwright operations.
- Use stable aliases such as `pka_announcements`, never native IDs in normal
  model calls.
- Project the tool catalog per principal: external users must not even see
  owner-only administration tools.
- Use closed JSON Schemas with `additionalProperties: false`.
- Prefer a tagged union with one discriminator over a large object containing
  mutually irrelevant optional fields.
- Avoid booleans whose meaning depends on another field; prefer explicit enums.
- Server defaults must cover the common path.
- Every response returns a short state, receipt reference and finite
  `next_action` enum.
- Error messages must identify one correct repair action without leaking secrets.
- Standard publication: one MCP mutation call after bootstrap/skill is cached.
- Publication with human visual choice: one initial call plus one selection/resume
  call.
- No blind retry after `outcome_unknown`.

### 6.3 Bootstrap/skill requirement

A method must immediately return the versioned VibePublish skill and enough
current runtime context for an agent to plan calls without exploring the entire
server.

The next window must compare and settle the best shape, for example either:

```text
vibepublish_get_started
```

or a narrowly equivalent bootstrap method. It should return:

- skill version, content hash and approximate token count;
- concise instructions or requested skill section;
- currently usable destination aliases/sets;
- granted surfaces and provider capabilities;
- platform formatting rules;
- retry/readback semantics;
- two or three minimal examples using the exact current schemas.

Expose the same skill as an MCP resource/prompt when supported, while retaining a
tool fallback for clients that cannot consume resources/prompts.

### 6.4 Candidate surface is not yet final

The earlier nine-method list is not canonical. A starting hypothesis to test,
merge or reduce is:

```text
vibepublish_get_started
vibepublish_publish
vibepublish_publication
vibepublish_visual
vibepublish_read
vibepublish_operation
```

Owner-only management may be projected separately. The final taxonomy must be
selected only after weak-agent task tests demonstrate that fields and method
choices are unambiguous.

## 7. Publication model

One semantic `publication_job` owns the whole cross-platform request:

```text
publication_job
|- semantic content
|- ordered immutable source assets
|- optional visual job / selected candidate
|- delivery policy and schedule
|- canonical digest
|- Telegram delivery
|- VK delivery
`- MAX delivery
```

Internal phases may include validation, rendering, persistence, asset upload,
provider execution and readback, but they are not separate model-visible calls.

Required states include:

```text
draft | validating | visual_running | needs_visual_selection
queued | scheduled | dispatching | provider_attempted
verified | partial | failed | outcome_unknown | cancelled
```

Every provider destination has its own child result. One verified success must
survive another provider's failure.

The idempotency digest binds principal, destinations, content, ordered asset
hashes, surface, schedule, visual preset/selection and provider overrides. Exact
replay returns the existing receipt; conflicting reuse is rejected before any
provider mutation.

## 8. Image generation and tuning

### 8.1 Required modes

The visual operation must support at least:

```text
generate  - create a new visual from a content brief
tune      - improve an existing rough/PIL-like visual
compose   - create a visual from several source images and constraints
select    - accept one generated candidate and resume a parent publication
```

The standalone visual operation and the `visual` section of publication must use
the same application service, not separate implementations.

### 8.2 `$imagegen` execution

Implement a durable job adapter around the verified Codex/DevCoveer route:

```text
VibePublish VisualService
-> ImagegenExecutor
-> `gpt-5.6-luna`
-> `$imagegen` task/invocation
-> returned image artifact(s)
-> immutable asset import
-> deterministic validation
-> candidates / publication continuation
```

Fresh-read and prove the exact invocation instead of guessing it. Persist
provenance:

- requested executor/model route;
- actual executor/model identifier when returned;
- prompt/preset version;
- source and output SHA-256;
- dimensions and media type;
- job/session reference;
- candidate decision and feedback.

### 8.3 Do not confuse tuning with model fine-tuning

The immediate product feature is image-to-image tuning and generation. True
model fine-tuning is a later capability. Nevertheless, store a clean preference
corpus from the first release:

```text
source draft
candidate outputs
accepted/rejected candidate
preset and prompt version
owner rating / rejection reason
content category
training-use permission
```

External tenant images are excluded from shared training unless the tenant has
explicitly allowed it.

### 8.4 Hybrid visual pipeline

Do not rely on the generator for exact Russian text, dates, addresses or logos.
Use `$imagegen` primarily for art/background/illustration/atmosphere and apply a
deterministic SVG/HTML/CSS or equivalent compositor for exact typography,
branding, safe zones and platform crops.

PIL may remain a technical utility for masks, resize and metadata, but it is not
the full design system.

### 8.5 Initial visual fixtures

Use the actual images from these posts as the first tuning fixtures:

- `https://t.me/kenigevents/4923`
- `https://t.me/lovekenig/12660`

The source cards are rough drafts, not positive training examples. Generate
multiple improved candidates, preserve the correct editorial information, select
an accepted result and store the complete source/candidate/decision lineage.

Prepare at least `4:5` post and `9:16` story derivatives. Validate exact text,
absence of accidental generated lettering in the art layer, logo integrity,
safe crops, selected asset hash and provider readback.

### 8.6 Presets

Presets are versioned visual recipes rather than simple filters. They may combine:

- imagegen prompt recipe and negative constraints;
- composition template and safe regions;
- deterministic typography and branding;
- aspect-ratio outputs;
- optional color grade, grain, texture or sharpening;
- source/media eligibility and training-use policy.

The architecture must allow later addition of reusable filter presets without
changing the MCP method taxonomy.

## 9. Reliability and security

Preserve the proven EventsBot properties while simplifying the model-facing
surface:

- encrypted opaque credential and provider references;
- immutable content-addressed assets;
- per-principal asset ownership;
- durable operation ledger and item-level checkpoints;
- leases/fencing for concurrent workers;
- provider timeout classification;
- read-after-write verification;
- `outcome_unknown` plus reconciliation rather than blind retries;
- media count/order/hash verification;
- compare-and-set for edit/reschedule where possible;
- secret redaction from prompts, traces and receipts;
- SSRF/MIME/size/decompression defenses on media ingress;
- cross-tenant denial tests.

MAX browser automation additionally requires persistent profile isolation,
screenshot/DOM evidence around guarded transitions, and a restart test proving
that an ambiguous click is reconciled rather than repeated.

## 10. DevCoveer target

A practical first deployment may use one persistent SQLite/WAL database and a
content-addressed asset directory; no separate distributed database is required
without evidence.

Suggested processes:

```text
vibepublish-api
  MCP + HTTP API + auth + asset serving

vibepublish-worker
  scheduler + imagegen jobs + provider delivery + reconciliation
```

Persistent state must include database, asset storage and isolated MAX browser
profiles. Secrets stay in DevCoveer environment/secret storage and never enter
GitHub.

## 11. Implementation sequence for the next window

1. Fresh-read current `vibepublish`, relevant IdeaHub packets and the EventsBot
   donor implementation/tests.
2. Treat this document's owner corrections as binding.
3. Materialize a canonical `social-visuals` requirement from
   `voice-20260904-165005-c0a0bcbe`; keep status explicit.
4. Build the natural-language task corpus and a machine-readable call/argument
   confusion matrix before selecting method names.
5. Design two or three competing minimal MCP surfaces and test them against the
   weak-agent corpus; choose the smallest surface with the fewest invalid calls.
6. Add versioned skill/bootstrap content and exact JSON Schema contract tests.
7. Implement domain/storage/assets/access/publication state machine.
8. Port only the reusable Telegram/VK provider logic and regression behavior from
   EventsBot.
9. Implement deterministic MAX Playwright adapter and fake-browser regression
   fixtures.
10. Implement `ImagegenExecutor` boundary and offline fake executor; do not fake a
    live `$imagegen` success.
11. Expose MCP and ordinary HTTP API over the same services.
12. Run offline unit, state-machine, schema, security, fake-provider and weak-agent
    tests.
13. Commit a coherent implementation checkpoint with docs and changelog.
14. Only then hand the exact checkpoint to Codex on DevCoveer for real
    `$imagegen`, credentials, MAX profile and live canaries.

## 12. Acceptance gates

The first implementation is not ready for DevCoveer live debugging until it
proves offline:

- zero provider SDK/browser choreography required from the model;
- zero raw provider IDs required in normal publication calls;
- zero cross-tenant reads/writes in adversarial tests;
- zero duplicate provider mutations under exact replay and worker restart;
- every ambiguous mutation becomes readback/reconciliation or
  `outcome_unknown`;
- standard publish requires one mutation tool call after cached bootstrap;
- visual-review publish requires no more than initial publish plus one
  selection/resume call;
- invalid method/argument rate is measured against a deliberately weak agent
  prompt corpus and is low enough to be operationally reliable;
- tool errors return one finite repair action;
- Telegram/VK/MAX partial fan-out preserves proven successes;
- image candidate lineage and selected SHA are durable.

Live acceptance on DevCoveer must then prove provider-backed post, media,
scheduling, edit/delete where supported, restart recovery, duplicate prevention,
MAX Playwright readback and real `$imagegen` artifact return through
`gpt-5.6-luna`.

## 13. Explicit exclusions for the current phase

- No MAX API-first rewrite.
- No direct Google Imagen/Gemini image API substituted for `$imagegen`.
- No verbatim copy of the 22-tool EventsBot Social Workspace catalog.
- No raw provider-method escape hatch.
- No separate Telegram/VK/MAX business services with divergent ledgers.
- No full external-user admin UI before the underlying access model works.
- No claim of live provider capability based only on donor source tests.
- No initial implementation delegated to Codex.

## 14. Ready-to-use prompt for the next ChatGPT window

```text
@GitHub

Продолжи анализ и затем начни самостоятельную реализацию VibePublish Social MCP.
Работай в onedayonemasterpiece/vibepublish напрямую через GitHub; первый кодовый
этап не делегируй Codex/DevCoveer.

Канонический handoff:
docs/features/social-operations/analysis-handoff-20260904.md

Сначала fresh-read:
- актуальный main vibepublish и весь handoff;
- docs/features/social-operations/README.md;
- docs/reference/events-bot-social-donor-map.md;
- перечисленные в handoff голосовые IdeaHub;
- фактические provider/runtime/tests доноры в events-bot-new.

Обязательные поправки владельца:
1. MAX сейчас реализуется через persistent Playwright profile на DevCoveer. Не
   переводить архитектуру на MAX API и не ждать его согласования.
2. Генерация/тюнинг изображений — через реально ранее проверенный `$imagegen`
   route в Codex/DevCoveer с запросом через gpt-5.6-luna. Не подменять это Google
   Imagen API. Exact contract сначала найти и доказать.
3. MCP методы спроектировать с нуля под слабую агентскую модель. Не копировать
   EventsBot tool catalog. До выбора методов составить natural-language task
   corpus и confusion matrix; проверить конкурирующие минимальные схемы.
4. Обычная публикация после получения/кэширования skill должна выполняться одним
   model-visible mutation call. Внутренние prepare/upload/commit/readback скрыты.
5. Должен быть bootstrap/skill method, сразу возвращающий versioned skill,
   approximate token count, доступные aliases/sets/capabilities и минимальные
   примеры точных текущих схем.
6. Поддержать Telegram, VK, MAX, собственные credentials пользователей и
   operator-shared credentials при точной admin/destination binding. Owner reads
   широкие; external reads по умолчанию отсутствуют и выдаются grants.
7. Визуалы: generate/tune/compose/select, несколько кандидатов, presets,
   immutable lineage и будущий preference/fine-tuning dataset. Первые fixtures:
   https://t.me/kenigevents/4923 и https://t.me/lovekenig/12660.

Сначала выдай продуктовый verdict по оптимальной MCP taxonomy и аргументам на
основе тест-корпуса. Затем зафиксируй requirements/docs и начинай применимый код,
тесты и skill в этом же окне. Финальная работа Codex будет только после offline
checkpoint для DevCoveer live integration и отладки.
```
