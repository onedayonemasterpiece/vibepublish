# Destination lifecycle, VK discovery, Stories and migration guarantees

Date: 2026-10-01. Contract: `1.7.0-runtime`.

Status at source checkpoint: implementation and offline regressions complete; production rollout and live acceptance are a separate gate recorded in [runtime status](../../operations/social-runtime.md).

This document is the canonical contract for destination discovery/persistence and the first native VK Story surface. It extends the existing [MCP contract](mcp-contract-v1.md) and [native forwarding/editorial profiles](forwarding-and-editorial-profiles-v1.md) without adding a new top-level MCP tool.

## Product invariant

**A provider-verified destination must not disappear after a VibePublish update, restart or redeploy while the provider connection and access remain valid.**

Destination identity and authorization are durable data, not release configuration. Runtime code may be replaced; the SQLite ledger containing `connections`, `destinations` and `bindings` remains authoritative. An upgrade must not recreate a registry from hard-coded aliases.

The normal product lifecycle is:

`explicit reference -> provider lookup -> verify provider identity/access -> verify required capability -> create or reuse durable destination -> create or reuse durable binding -> publish/read normally`.

A subsequent exact resolve is idempotent and returns the existing stable alias. It may refresh provider label/handle and may add newly verified rights, but it never silently reactivates a revoked binding.

## Exact destination resolve

`vibepublish_destinations(command.kind=resolve)` is owner-only discovery. It accepts exactly one explicit provider reference:

- an HTTPS provider URL;
- or a provider-native numeric ID where supported.

It does not enumerate the operator account, list unrelated resources or turn a public URL into publishing authority.

### Telegram

Telegram keeps the existing read-only exact resolve path. It checks the supplied public/invite/internal reference against the already connected MTProto user, proves membership and ordinary publish permission, and never joins a chat as a discovery side effect.

### VK

VK exact resolve accepts canonical `vk.com` / `vk.ru` community URLs or a numeric community ID. A URL handle is sent to `groups.getById` as a handle; it is not coerced to an integer.

For the resolved community VibePublish verifies:

1. exactly one community identity was returned;
2. the user-token connection currently has sufficient community administration authority;
3. the configured transport can exercise `wall.post`;
4. other lifecycle rights are granted only when their concrete VK method is permitted by the configured transport.

The persisted native target is the negative community wall identity (`-<group_id>`). The opaque runtime alias is derived from connection identity plus native target, for example `vk_<digest>`; it is stable across process restarts and deployments because the binding row is durable.

An unauthorized community fails closed and creates no destination/binding row.

## Persistence and migration

The durable ledger separates:

- `connections`: provider/account identity and secret reference;
- `destinations`: connection + native provider target + current label/handle;
- `bindings`: principal + stable alias + destination + rights + epoch.

Deployments must point server and worker at the same existing ledger. Release source directories are immutable code artifacts; they are not the destination registry.

Migration rules:

- never drop/reseed destination tables merely because a new release is installed;
- never make a previously verified binding disappear because an adapter gains a new discovery implementation;
- preserve alias, destination ID, binding ID, rights and epoch unless a deliberate migration explicitly changes their representation;
- stale/revoked bindings remain revoked; exact resolve cannot silently reactivate them;
- provider access revocation is handled as `access_revoked` / reauthorization, not as registry deletion;
- a production release must be restart-tested with previously resolved destinations before acceptance.

This directly protects the regression where `lovekenig_vk` survives while other previously verified VK destinations must not vanish on a runtime upgrade.

## Destination search

Account-wide discovery is not required for ordinary publishing. `search` may remain unavailable until a provider-bounded implementation is proven.

Exact resolve by explicit URL/ID is the supported no-administration workflow. A caller must not be forced to edit server configuration merely because it names a new owned community explicitly.

## Capability evidence

Capability output is evidence, not static documentation.

For a binding/surface, `supported` may be returned when the current binding epoch has recent durable evidence of a successful provider mutation confirmed by exact provider readback. For Telegram post preview, the existing provider preflight evidence remains valid without dispatch.

A historical absence of a canary must not permanently leave an actually live-accepted surface at `needs_review`. Conversely, a source implementation or offline fixture alone must not promote a live capability.

The first VK capability surfaces are independent:

- `post`;
- `story`.

A successful post does not prove Story support and a successful Story does not prove wall-post support.

## VK Story surface

Native photo Stories use the existing `vibepublish_publish` tool with `surface=story`. No separate Story tool is added.

The first supported shape is intentionally narrow:

- VK community destination;
- immediate publication only;
- exactly one verified image asset;
- PNG/JPEG/WebP;
- no authored Story caption text in this first contract;
- no native Story scheduling claim;
- no Story forward/repost analogue.

Provider flow:

1. preflight community administration and method permissions;
2. `stories.getPhotoUploadServer(group_id=...)`;
3. upload the verified image to the returned allowlisted HTTPS endpoint;
4. persist the dispatch boundary;
5. `stories.save(upload_results=[...])`;
6. obtain the exact Story owner/id;
7. read back that exact identity with `stories.getById(stories=[owner_id_story_id])`;
8. verify target and provider media binding;
9. return a normal VibePublish item reference with namespace/kind `story`.

Deletion uses normal `vibepublish_publication_update(change.kind=delete)` against the tracked publication or scoped `item_ref`. It calls `stories.delete` and then verifies exact absence with `stories.getById`.

If the provider reports that a community is ineligible for Stories (for example provider-side community requirements), that is a provider capability failure for that destination; VibePublish must not simulate a Story through a wall post or browser workaround.

## VK native repost

VK native repost remains `vibepublish_engage(command.kind=forward)` with a verified VK wall source and VK destination. It uses `wall.repost`, preserves provider attribution/copy history and verifies the exact destination wall item.

A copied authored post or plain link is not a repost success. Scheduled VK repost remains unsupported until VK exposes and VibePublish proves a genuine provider-native scheduled repost path.

## Readback and unknown outcomes

A local receipt is not provider success.

For VK wall deletion, exact provider absence includes the documented/observed tombstone form returned by `wall.getById`: a row for the same wall-local ID with `is_deleted=true`. That row is deletion evidence, not a live post. VibePublish must not repeat `wall.delete` merely because VK retains this tombstone.

Posts, Stories and reposts complete only after exact provider readback. After the durable dispatch marker, a timeout or malformed/missing identity is `outcome_unknown`; it must be reconciled, not repeated with a new request key.

Story namespace is distinct from the normal immediate wall namespace:

- wall post: `published`;
- postponed wall post: `scheduled`;
- Story: `story`.

Core verification checks the namespace expected by the requested surface. This prevents a Story from being rejected merely because generic post logic expected `published`, without weakening wall-post invariants.

## Troubleshooting

### `capability_not_implemented` on VK resolve

Verify the deployed release contains the provider-neutral destination resolver and `adapters/vk_discovery.py`. A Telegram-only runtime overlay is not sufficient.

### VK URL resolve fails before provider lookup

Check that the transport does not coerce `groups.getById.group_ids` to an integer. Handles such as `kenigeventsofficial` are valid exact selectors.

### Resolve succeeds but destination disappears after restart

Confirm server and worker use the same persistent SQLite ledger and that deploy scripts did not create a fresh DB. Inspect `connections`, `destinations`, `bindings` identity/epoch, not hard-coded bootstrap aliases.

### `needs_review` remains after a verified live canary

Capability projection must read current-epoch durable attempt/readback evidence. A static “no canary verified” string is not authoritative after a successful exact provider readback.

### Story submit is uncertain

Do not send another Story. Observe the original checkpoint/Story identity. Only a proven provider outcome may resolve the attempt.

## Acceptance gate

A release is product-ready for this change only after all of the following are observed on the actual deployed runtime:

- Telegram exact resolve regression passes;
- both requested VK community URLs resolve;
- second resolve reuses each binding;
- destinations survive worker/server restart;
- VK wall post succeeds with exact provider readback;
- VK Story succeeds with exact provider readback;
- VK native repost succeeds with origin attribution readback;
- test live entities are removed only through normal lifecycle operations after their outcomes are known;
- bootstrap exposes current destinations and evidence-based per-surface capabilities;
- source/unit/integration suites are green;
- the deployed release identity is recorded in runtime evidence.

Do not mark the live gate complete from source tests alone.
