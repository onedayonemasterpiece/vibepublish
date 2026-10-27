# Publication recovery: automatic worker outcome

Status: **W1 source change; offline tests only.** Live provider acceptance and deployment are separate.

## Normal publishing path

A publication is one accepted immutable command with independent Telegram, VK
and MAX attempts. The worker owns completion within the original absolute budget:
15 minutes after acceptance for an immediate command, or the requested provider
schedule minus its native submission lead. Waiting for the connection lane and
preflight consume the same budget; retries never move the deadline.

- Before the dispatch marker: only explicitly classified transient provider/transport
  codes retry with fixed age-based backoff (5/15/30/60 seconds). Invalid input, expired native lead time, missing authorization
  and revoked rights produce an explicit failure. A failing provider never blocks
  an authorized sibling.
- After the dispatch marker: the same attempt goes to the adapter's
  `reconcile`, never to a fresh `execute`. VK's adapter is responsible for
  searching its original postponed item and, if appropriate, reusing the
  original `guid`; Telegram and MAX retain their own exact recovery behavior.
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
