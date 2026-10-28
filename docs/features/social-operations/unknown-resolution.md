# Publication recovery: automatic worker outcome

Status: **W1 + W4 source changes; offline tests only.** Live provider acceptance and deployment are separate.

## Normal publishing path

A publication is one accepted immutable command with independent Telegram, VK
and MAX attempts. The worker owns completion within the original absolute budget:
15 minutes after acceptance for an immediate command, or the requested provider
schedule minus its native submission lead. Waiting for the connection lane and
preflight consume the same budget; retries never move the deadline.

- Before the dispatch marker: only explicitly classified transient provider/transport
  codes retry with fixed age-based backoff (5/15/30/60 seconds).
  A Telegram FloodWait/SlowModeWait is not retried until its recorded
  `retry_after_s` has elapsed (or the ordinary backoff, whichever is later).
  The adapter attaches the cooldown to its `DomainError`; worker.fail
  persists it in the same attempt result as `missing_checks`, and the existing
  retry scheduler reads that result directly. No event-log parsing or new timer.
  Invalid input, expired native lead time, missing authorization and revoked
  rights produce an explicit failure. A failing provider never blocks
  an authorized sibling.
- After the dispatch marker: the same attempt goes to the adapter's
  `reconcile`, never to a fresh independent `execute`. VK's adapter searches
  its original postponed item and may reuse its original `guid`. For Telegram
  publish/forward, the checkpoint stores `random_id` values before the send:
  if a response was lost before native message IDs were saved, reconcile replays
  the original MTProto request using **those same random IDs**. Telegram
  deduplicates them across account sessions and returns the original message
  identity. The adapter then reads the exact native history/queue item by ID,
  never by text similarity. Already checkpointed IDs are only read, not resent.
  An unresolved response remains within W1's bounded retry/deadline and ends
  with a clear refusal if no native ID is recovered.
- A saved native post ID proves provider acceptance. The worker re-reads that ID
  while time remains; if readback is still unavailable at the deadline, the
  published/scheduled result contains the original ID, a URL only if provided by
  the adapter, a private item/queue reference and a short event warning.
- If no provider identity can be established by the deadline, the attempt ends
  `blocked` with `publication_unconfirmed`. It is not automatically sent again
  after expiry. No terminal `outcome_unknown` and no `review_outcome`
  instruction is generated in this worker path.

There is no cross-publication connection quarantine: another valid post on the
same VK, Telegram or MAX connection can proceed. Worker lease fencing, durable
dispatch, provider lane and any existing provider finalization/quarantine on the
*same attempt* remain.

## Legacy uncertain attempts and explicit APIs

Historical `outcome_unknown` rows, `publication_update.reconcile_removed`,
and the additive original-terminal recovery schema predate this policy and are
not deleted or rewritten by W1. These historical recovery APIs do **not** serve
as a required extra step for current publishing. The normal path never waits
for a person to validate the existence of a post.

VK media-copy diagnostics from earlier releases may still be available in
historical events, but cannot block another publication. A positive native post
ID is sufficient for publication success under the current product decision.

Validation: deterministic worker fake-provider failure injection; no live
social-network calls, no production database writes, no deployment.
