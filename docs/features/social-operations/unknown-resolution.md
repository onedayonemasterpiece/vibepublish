# R17 — externally removed uncertain native scheduled publication

Status: **Fixed** owner intent (finish safe native scheduling); implementation **Not confirmed by user**.

Delta to the social-operations unknown-outcome quarantine: add an owner-only,
read-only `publication_update` change `reconcile_removed`, naming an exact old
attempt. This does not retry, delete, cancel, or verify the original publication.
A complete current scheduled queue plus an exact published-namespace lookup must
both prove the checkpoint-bound native object absent. Missing or invalid bound
checkpoint, pagination that cannot finish, collisions, inaccessible provider,
foreign ownership, or revoked authority leave the original quarantine intact.

A new immutable resolution proof records actor and binding epochs, original
attempt and checkpoint digest, exact destination/native object, observed absence,
and operation. Original unknown operation and attempt remain unchanged. Only that
resolved attempt is excluded from subsequent connection quarantine. Request keys
are idempotent; publication revision uses CAS. No manual database reset.

## API and evidence

Call `vibepublish_publication_update` with:

```json
{"publication_id":"pub_…","expected_revision":2,
 "change":{"kind":"reconcile_removed","attempt_id":"attempt_…"},
 "request_key":"unique-resolution-key"}
```

Only the same private publication's current owner can request this bounded VK
scheduled-publish resolution. For the ordinary native-object case, checkpoint
transitions `vk_response` or `vk_media_bound` must bind a positive native ID,
immutable plan digest, attempt and target. A historical id-less scheduled
`publish` may use `vk_prepared` only under the stricter absence-proof rules
defined below; no edit/reschedule or generic unknown gains that exception. The
worker holds the connection lane through reads and proof commit, bounds
pagination to 100 pages / 30 seconds, checks authority again before commit, and
never calls prepare/execute/reconcile. A verified resolution receipt proves only
the bounded absence claim; it does not claim publication/cancellation. Durable
proof is in `attempt_resolutions`, indexed by exact old attempt and new operation
ID. Original receipt remains unknown; the resolved attempt cannot subsequently be
edited/retried from the absence proof. A separate explicit publish is required.

SQLite schema migration is additive version 4 and included in package data.
Validation: 10 dedicated tests pass; broader runtime/contracts/verification and
visual-recovery tests passed (101 tests and 199 subtests).
Live acceptance is root integrator responsibility, not proven by these fixtures.

The original dispatched operation's actor epoch must also equal the current
authenticated owner epoch at admission and proof commit. Reauthentication after
an epoch change does not authorize resolving an earlier-epoch uncertain effect.
Regression: fresh authenticated owner after epoch bump is denied before reads or
revision changes; original attempt and quarantine remain intact.

## Historical id-less scheduled publish quarantine

Status: **Not confirmed by user**. This is a narrow additive R17 recovery for a
historical VK scheduled `publish` that crossed the durable dispatch boundary but
lost the `wall.post` response before a positive native post ID was checkpointed.

Eligibility requires the immutable original attempt to be `outcome_unknown`,
`dispatched=1`, provider VK, scheduled `publish`, transition `vk_prepared`,
matching attempt/plan/target checkpoint identity, non-empty frozen text, and media
cardinality matching the frozen plan. Edit/reschedule and other actions remain
ineligible without a positive native ID.

`reconcile_removed` still performs **no provider mutation**. For an eligible
id-less attempt it must enumerate the complete postponed queue and reject
resolution if an item with the exact frozen text and scheduled time is present.
It must also exhaust a bounded complete provider published feed and reject resolution when an item
has the exact frozen text, or when pagination is incomplete/stale.
Only when both observations complete with no matching effect may the service
record `scheduled_intent_absent`, with `native_id: null`, queue/feed digests,
and the original checkpoint digest. The original operation remains
`outcome_unknown`; only its connection quarantine is released. This proof never
authorizes a replacement publication, retry, edit, cancel, or delete.

## Final verified copy evidence

When a VK adapter observes an exact user-photo → community-photo copy, final
worker checkpoint persistence retains `remote` and a bounded `provider_evidence`
record (`kind: vk_photo_copy`). Per-ordinal saved/current provider IDs and exact
rendition SHA-256, byte size, MIME, width and height remain auditable after success.
Attempt/plan/target/native-ID bindings and ordinal mappings are validated again.
Arbitrary adapter keys and rendition URLs are not copied to this final proof.
Non-VK final checkpoints remain unchanged. Three worker integration/scope tests
cover successful persistence, malformed mapping rejection and non-VK isolation.

## Narrow scheduled lifecycle delta

Status: **Not confirmed by user**. The same absence proof may resolve an uncertain
scheduled `edit` or `reschedule`, but only when its immutable `plan.existing`
identifies the same scheduled native target and native ID as its response
checkpoint. Missing existing binding, published namespace, different target or ID,
and actions other than publish/edit/reschedule are ineligible. All original
actor/binding epoch fences remain; no lifecycle call is retried and the original
unknown attempt is preserved. This enables safe reconciliation after an owner
separately removed the exact test object, not a generic quarantine bypass.


## R18 - same-operation VK scheduled fan-out completion

Status: **Not confirmed by user**. Source/runtime regressions are green; live TG+VK acceptance is still required before owner confirmation.

This is distinct from `reconcile_removed`. It never declares an unknown object externally removed and never authorizes a new publication. For one original ordinary VK scheduled `wall.post` attempt:

- a pre-dispatch transient provider/transport failure may re-admit only that same immutable attempt, with bounded retry count and short durable backoff;
- after the durable dispatch marker, the adapter may first read the complete postponed queue and recover one exact frozen match;
- if no exact frozen match exists, the adapter may repeat only the identical `wall.post` under the same deterministic VK `guid`, and only when the prepared checkpoint proves that the attachment list is capability-free and exactly reconstructable;
- the same operation/attempt identity, plan digest, target, text, media IDs and requested provider-native time remain fixed;
- successful Telegram or other siblings are terminal and are never re-executed while VK recovery proceeds;
- worker restart preserves this recovery path because retry count, attempt checkpoint and operation identity are durable.

Multiple exact queue matches, changed authority, expired native submission window, unsafe/non-reconstructable media, lifecycle actions, exhausted bounded attempts or any mismatch stay `outcome_unknown`. Agent-side resubmission with a fresh key remains forbidden.