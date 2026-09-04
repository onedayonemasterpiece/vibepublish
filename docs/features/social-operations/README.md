# VibePublish Social Operations

Owner requirements: `Fixed`, 2026-09-04.

Engineering design: `Not confirmed by user`; selected implementation baseline, not a claim of owner sign-off or empirical model optimality.

Runtime implementation: `Not done`.

## Read in this order

1. [Independent audit and source evidence](../../reports/vibepublish-audit-20260904.md).
2. [Implementation design: architecture, data, reliability, MAX, security and delivery gates](implementation-design-v1.md).
3. [MCP contract, taxonomy, exact arguments and measured offline checks](mcp-contract-v1.md).
4. [Social visuals / imagegen](../social-visuals/README.md).
5. [EventsBot donor map](../../reference/events-bot-social-donor-map.md).

The [2026-09-04 handoff](analysis-handoff-20260904.md) remains historical source evidence and preserves the owner's corrections. Its candidate method list and unresolved engineering alternatives are superseded by the implementation design and MCP contract. The old nine-method list is no longer a competing canonical API.

## Goal and ownership

VibePublish is an independent social-network operations service on DevCoveer. ChatGPT, LADENO, EventsBot and other clients access the same application services through MCP or HTTP. VibePublish owns provider adapters, credentials/session references, principals and tenant grants, destination aliases/sets, semantic content/renderings, immutable assets, scheduling, durable operations, verification, receipts and audit.

EventsBot donates implementation and regression behavior; it is not a runtime dependency. Event-domain rules and editorial choices remain in EventsBot. After verified migration it calls VibePublish rather than retaining a second independent social execution backend.

One logical publication may fan out to Telegram, VK and MAX, with a separate persistent result for each destination. Transport success is not publication proof. Provider differences remain explicit rather than reduced to the weakest shared format.

## Binding provider decisions

### Telegram

Use independent VibePublish connections and the proven Telethon owner-session path. The canonical owner session namespace is `VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE`. No fallback to EventsBot/E2E/unrelated sessions is permitted. Bot API/business connections may be supported separately where their actual capabilities are proven.

Preserve rich text/entities, named links, registered custom emoji, media and albums, messages/Saved Messages, stories, scheduling, edits/deletes and allowed reads/analytics. Actual rights and capability evidence apply per connection/destination/surface.

### VK

Use VibePublish-owned role-scoped connections and credentials in a VibePublish namespace. Preserve reader/messenger/publisher/media/story role separation where required; one physical credential may satisfy multiple roles if verified. Port proven transport, upload/save, provider readback and error classification without importing EventsBot runtime state.

### MAX

**MAX remains Web/Playwright. There is no MAX API requirement or API approval dependency for the current release.** Use an isolated persistent account profile and deterministic specialized driver with guarded submit and provider-visible readback. A general-purpose browser agent is not the production publisher.

The implementation design defines exact target/account verification, one profile execution lane, durable dispatch checkpoint, recovery limits and ambiguous-outcome handling. Optional model-assisted locator recovery is deferred until deterministic paths work and cannot submit, delete, choose targets, alter content/time or solve authentication challenges.

## Access and administration

Owner reads may reach anything actually visible to the connected account, not just a predeclared shortlist. Writes still require actual provider rights and all identity/reliability checks.

External principals have **no social reading by default**, including on their own connection, until explicit destination/operation read grants are issued. They may inspect their own operational receipts and assets. Internal verification of a write must not expose surrounding private feed content.

Both onboarding models are mandatory:

- Tenant-owned credentials/sessions: isolated, encrypted at rest, securely provisioned and independently revocable.
- Operator-shared credentials: an owner-created exact destination binding plus real provider publisher/admin rights. Supplying a channel URL, name or native ID never grants access.

Tenant boundaries, quotas, credential separation, policy epochs and revocation belong to the first core implementation, not a final retrofit. A full admin UI can wait; initial owner-only CLI/secure onboarding is sufficient. External users must never send provider secrets in normal model-visible arguments.

## Destinations and content

Keep connection, destination and destination_set separate. Aliases are stable and tenant-scoped. Accept one or more explicit aliases or sets, freeze the concrete target snapshot, and recheck authorization before actual dispatch. Add/remove/rename/list sets without changing queued jobs' targets.

The canonical content model supports paragraphs, emphasis, links, mentions, hashtags, emoji and captions/alt text, ordered media and explicit provider renderings. Normal calls use plain text or a bounded Markdown subset; SDK entity offsets are internal. Telegram named links, VK visible URLs and MAX's proven formatting are rendered separately. No silent loss of media, links or text and no unapproved splitting into several posts.

Default adaptation is deterministic. Optional model editing produces a new reviewable revision before dispatch; it cannot change business intent during provider execution.

## Capability baseline that must be preserved

Do not interpret the first working slice as permission to discard broader verified donor behavior. The full product baseline includes, wherever the bound provider connection supports it:

| Family | Required coverage |
|---|---|
| Discovery/read | Exact target/item resolution, target and dialog search/listing, feed/history/search, exact posts/messages/comments/stories with usable media references |
| Observation | Comments/replies, reactions, stories/statistics, scheduled queue, notifications/mentions, audience/post/story/community analytics, editorial sampling and provider recommendations |
| Publication | Direct and Saved Messages, channel/group/community/wall posts, rich formatting, single and ordered multiple media/albums, image/video/audio/animation/document |
| Lifecycle | Immediate, durable service and proven native scheduling; scheduled listing/reschedule/cancel; edit/media replacement/delete; forwarding/reposting |
| Engagement/stories | Comments/replies, add/remove reactions, photo/video stories and typed native options |

Capabilities use supported/unsupported/needs_auth/needs_review/temporarily_unavailable plus observation time/evidence. Do not hide working functionality with an unrelated global product flag. Do not advertise a donor capability as live before independent VibePublish adapter verification. Typed native extensions are added with exact schemas and tests before activation; raw provider passthrough is prohibited.

## MCP and service API

The selected task taxonomy has eight methods:

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

A publisher-only client sees five core methods. No separate story/schedule/video synonym tools and no model-visible prepare/commit sequence. One complete authorized publication requires one mutation call; a human visual choice needs the initial call and one selection/resume call. Status polling is observational.

All exact names, tagged arguments, closed input/output schemas, errors, HTTP mapping, grant projection and skill/bootstrap semantics live in [MCP contract v1](mcp-contract-v1.md), not duplicated here. The versioned [skill](../../llm/vibepublish-social-skill.md) is served as resource/prompt and through the fallback get_started tool.

## Reliability requirements

Each request owns a durable parent and per-destination children. Distinguish request identity from frozen execution-plan identity so generated assets and candidate selection do not break replay semantics. Exact replay returns the original receipt; conflicting reuse is rejected; uncertain side effects are never blindly repeated.

Preflight all deterministic target/content/media errors before sending any child. Once external execution begins, preserve partial successes and do not promise atomic cross-platform rollback. Persist the dispatch boundary before the side effect. Expired leases and restarted workers do not justify repeating an uncertain send.

Separate accepted, service queued, provider scheduled and observed published. Default scheduling is the service queue, with explicit timezone and late policy; native scheduling is optional and has one responsible backend per child. Cancel unsent work and delete published work are distinct. Revocation must address already-submitted native schedules and report residual remote risk honestly.

Source hashes prove the uploaded input; transcoded provider media need object-binding and semantic/order/count evidence, not a fabricated identical remote SHA. Missing verification remains visible. Edits use revision checks and detect external manual changes.

The implementation design is canonical for state transitions, receipts, retry/reconciliation, assets, quotas, security, backups/restore and scheduler migration.

## Related media products

[Social visuals](../social-visuals/README.md) implements generate/tune/compose/select through the required `$imagegen` route requested via `gpt-5.6-luna`, with actual route/artifacts proved later on DevCoveer. Google Imagen is not a substitute. Exact text uses deterministic composition; tenant training consent is separate.

[Video stories](../video-stories/README.md) preserves the original Telegram-controlled Kaggle video generator, voice comments, geo/time filtering, music, subtitles, safe enhancement and mandatory approval. It supplies verified assets to the same social service, not another publisher or queue.

## Delivery and acceptance status

**Completed design work, not runtime:** audit, architecture/data/recovery/security decisions, selected MCP grammar, executable schemas, 80-task golden corpus, 20 negative cases and a versioned skill. Eight offline contract test methods passed. These are not weak-model, database, browser or live-provider tests.

**Not done:** domain/storage/auth/worker runtime; independent Telegram/VK/MAX adapters; actual imagegen executor; real MCP/HTTP server; donor capability parity; external onboarding; live canaries; EventsBot cutover; video generator.

Implementation batches A–F and V and their blocking tests are defined in implementation-design-v1.md. Initial implementation remains direct ChatGPT/GitHub work. Codex is reserved for later DevCoveer environment integration, real imagegen verification, MAX live-driver debugging and controlled canaries. No Codex task was invoked for this audit/design package.
