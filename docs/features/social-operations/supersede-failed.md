# Explicit replacement of never-dispatched failures

Status: **Not confirmed by user**. Offline regression coverage is available;
this status does not claim production activation or provider acceptance.

## Scope

Use `vibepublish_publication_update` with the original `publication_id`,
`expected_revision`, a stable `request_key`, and a closed change:

```json
{
  "kind": "supersede_failed",
  "destinations": ["vk_channel"],
  "content": {"text": "Corrected publication text"}
}
```

This is an explicit content-changing replacement of selected original publish
attempts that are `blocked` or `failed` with durable `dispatched=0`.
It is not a retry of edited frozen bytes. Ordinary `retry_failed` remains
content-preserving, but transient pre-dispatch errors are now automatically
retried within the original fixed horizon and need no such request. No dispatched, uncertain, successful, scheduled, cancelled,
or active selected attempt is eligible. An active selected attempt or pending provider finalization of that
selected object prevents replacement; unrelated network attempts do not. Native-item references, prior edits,
forwards, and preview intents are excluded.

Either current publish or publication-management scope is required, along with
current publish rights on each selected binding. A publish-only principal sees
only its bound publishing aliases and gains no edit/delete/reconcile permission.
Ownership and actor/binding epochs are rechecked, including receipt replay.

## Effects and preserved evidence

Admission creates a separate linked publication at revision 1 and ordinary
publish attempts for the selected destinations only. The new immutable request
records the source publication, operation, revision, and selected attempt IDs.
The returned standard receipt identifies the replacement, and events on both
operations explain the lineage.

Only content changes. Existing verified private assets, native requested time,
surface, and topic are retained and revalidated. Expired native timing is rejected;
it is never silently converted to immediate delivery. Normal content compilation,
asset integrity, quotas, authorization and per-attempt dispatch fencing apply
to the replacement. There is no connection-wide outcome-unknown fence.

Selected original attempts become locally cancelled before any dispatch. Their
immutable plans/digests, original failure results, checkpoints, request, and
revision remain unchanged. A source-operation event records why they were
superseded and identifies the replacement. They cannot be retried or superseded
again. This cancellation describes the local never-dispatched intent; no native
queue cancellation is performed. Successful siblings, including already-scheduled
Telegram children, retain their rows and native objects unchanged. The historical
source operation retains its outcome summary.

## Atomicity and recovery

One SQLite write transaction checks the source revision, terminal operation,
selected states, zero-dispatch markers, authority, and immutable binding identity;
creates the replacement; disables the selected old children; records lineage; and
binds the request key. Original-operation fencing invalidates stale worker hooks.
Concurrent retry, replacement, or worker admission cannot submit both intents.

Replay with the same key/content returns the same replacement receipt, including
after the replacement itself fails. Changed content under that key conflicts.
Never automatically create new request keys to repeat a failed or uncertain
replacement. A subsequent replacement requires a new explicit user decision and
must independently satisfy the same zero-dispatch conditions.

This narrowly bounded route does not relax the existing prohibition on creating
replacement operations for uncertain dispatched effects. Such effects still
require observation or the applicable explicit reconciliation workflow.
