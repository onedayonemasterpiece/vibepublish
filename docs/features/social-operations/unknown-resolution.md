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
scheduled-publish resolution. Checkpoint transitions `vk_response` or
`vk_media_bound` must bind a positive native ID, immutable plan digest, attempt
and target; `vk_prepared` is insufficient. The worker holds the connection lane
through reads and proof commit, bounds pagination to 100 pages / 30 seconds,
checks authority again before commit, and never calls prepare/execute/reconcile.
A new verified receipt explicitly says **externally removed**, not published or
cancelled. Durable proof is in `attempt_resolutions`, indexed by exact old attempt
and new operation ID. Original receipt remains unknown; this removed publication
cannot subsequently be edited/retried. A separate explicit publish is required.

SQLite schema migration is additive version 4 and included in package data.
Validation: 10 dedicated tests pass; broader runtime/contracts/verification and
visual-recovery tests passed (101 tests and 199 subtests).
Live acceptance is root integrator responsibility, not proven by these fixtures.

The original dispatched operation's actor epoch must also equal the current
authenticated owner epoch at admission and proof commit. Reauthentication after
an epoch change does not authorize resolving an earlier-epoch uncertain effect.
Regression: fresh authenticated owner after epoch bump is denied before reads or
revision changes; original attempt and quarantine remain intact.

## Final verified copy evidence

When a VK adapter observes an exact user-photo → community-photo copy, final
worker checkpoint persistence retains `remote` and a bounded `provider_evidence`
record (`kind: vk_photo_copy`). Per-ordinal saved/current provider IDs and exact
rendition SHA-256, byte size, MIME, width and height remain auditable after success.
Attempt/plan/target/native-ID bindings and ordinal mappings are validated again.
Arbitrary adapter keys and rendition URLs are not copied to this final proof.
Non-VK final checkpoints remain unchanged. Three worker integration/scope tests
cover successful persistence, malformed mapping rejection and non-VK isolation.
