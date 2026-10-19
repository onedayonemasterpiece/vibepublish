# Exact legacy-entry reads

Requirements: `Fixed` for the owner's four canonical Regional Knowledge archive
originals and separately enumerated thirty historical illustration entries. Owner acceptance status: `Not confirmed by user`. Implementation and scoped live byte verification are complete on release `d1f880b24788f609398a660ba53dd8c4731b7aec` (#84), API and worker, schema 11. The independent 19 October check reconstructed all 34 current exact grants, downloaded three active legacy images through RKB MCP, and downloaded all four legacy PDF originals through RKB's dedicated loopback service client; each actual SHA matched its pinned proof. See the [RKB acceptance report](https://github.com/onedayonemasterpiece/regional-knowledge-base/blob/13c5354/docs/reports/illustration-archive-live-acceptance-20261019.md). This status does not authorize additional entries or call source/test preparation runtime acceptance.

## Boundary

This is a read-only exception for an already existing technical principal, not
publication reassignment or a new sharing surface. No credentials, owner scope,
binding, provider message, document clone, service, or queue is created.
List/search keep their existing publication-principal boundary. The service
cannot use generic item reads to bypass its narrow media-store tool scope.

Separate private operator manifests contain exactly the four approved canonical
originals and the thirty approved historical illustration entries, not duplicates.
Neither manifest is committed. Public fixtures are synthetic. No other owner
media gains access. The per-call limit remains four grants; a frozen thirty-entry
manifest uses eight bounded calls in the same transaction after validating the
complete set and refusing unexpected existing grants.

## Durable authorization

Schema 11 adds exact grant records and temporary-asset-to-grant links.
A grant contains a frozen proof of the current target tenant/principal and epoch,
binding ID/epoch, connection and destination, source publication owner/revision,
Telegram chat/topic/message/attachment identity and immutable origin. Current
origins retain their explicit SHA interpretation unchanged.
A grant never derives authority from an origin URI or Telegram link alone.

Get admission checks current proof before keyed replay or fresh admission.
The existing durable operation stores the immutable grant ID, including no-key
reads. Status, replay, the worker before provider access and after download, and
each byte-cache read revalidate that same grant. Revocation deletes the grant;
regrant creates a different ID and cannot revive an old operation or cache.

The worker accepts exactly one source document at the exact native identity and
topic, and hashes actual downloaded bytes against the pinned provider SHA.
Unexpected/extra documents, changed source revisions, revoked topic/binding,
foreign tenant/principal and mismatched bytes fail closed before cache insertion.
The existing one-hour cache remains temporary. No document is republished.

## Historical illustration origin v1

The legacy-v1 compatibility path is deployed and byte-verified for the approved active archive sample. It is no longer an unimplemented ownership-mismatch blocker.
It is explicit, not a chain of fallback hash guesses: origin has exactly
`system=regional_knowledge` and `ref=knowledge://illustrations/<UUID>`, with no
SHA field; the source is in native topic 4 with one document attachment and one
canonical slot-zero `download_sha256` image observation. Missing, malformed or
ambiguous evidence and native photos fail closed. Any nonempty media hashes must
equal that observed digest. A present malformed/conflicting origin SHA never
switches to this legacy interpretation.

The grant pins the fact ID and canonical observed SHA/MIME/size/slot/kind, not the
mutable snapshot or observation timestamp. Normal readback refreshes must not
invalidate its own receipt/cache. Source, display and provider crop SHA roles
remain distinct: only the exact manifest's provider SHA may match the pinned
observed evidence. No immutable intent, origin or native bytes are rewritten.
Actual returned document bytes, MIME and size must match the pinned observation
before cache insertion; cache serving uses the same explicit proof digest.

Before each live legacy grant, verify the exact native topic-4 document and its
actual bytes through an already authorized path. Historical metadata agreement
alone is not that verification. If no authorized path is available, keep the
entry pending; do not impersonate the owner or bypass the existing ACL.

## Migration and release gate

The schema-11 rollout and exact 30-image / 4-original grant installation have already completed on #84. Do not repeat migration or grant application merely because an older audit describes them as pending. The following are safeguards for any future deployment or recovery.

This change is not compatible with an API-only rollout. Old workers do not know
the grant guard and old Store initialization rejects schema 11. Do not initialize
the new Store on the live ledger, admit shared reads or apply grants until:

1. The exact candidate and schema-11-compatible rollback source pass review and
   required checks. Complete the separately released baseline and verified topic-4
   acceptance first.
2. The actual systemd unit dependency/restart coupling is understood. Obtain a
   coordinated idle/drain window without interrupting unrelated active commands.
3. Both server and worker actual PIDs, command lines and immutable release roots
   prove the reviewed candidate is loaded, not merely configured. Preserve active
   ledger operations and existing provider session exclusivity.
4. Perform the migration only in that coordinated window; verify integrity and
   preserved operation/publication identities before any grant.
5. Verify the existing service is non-owner with exactly its original narrow
   scopes and binding. Recheck the selected exact manifest's frozen proofs transactionally, refuse
   unexpected existing entry grants, and apply only the reviewed exact set.
6. Read each canonical source through the existing service identity, await its
   original operation, then verify the actual asset SHA. Verify denied foreign
   entry/topic/tenant/principal and revoked-grant cases with synthetic fixtures.

Future runtime work remains coordinator-gated by topic-4 acceptance, disk admission and
an independently verified worker window; green source CI is not runtime approval. Draft #87 is source-only recovery material, not an instruction to merge, downgrade schema or switch the live worker.

## Recovery without schema downgrade

Before live migration, prepare and test a stable PR80+83+85 rollback candidate which
accepts the additive schema 11 but denies grant-marked read operations at both
worker and private-status boundaries. It must also deny every foreign-source
download cache even if an unrelated publish scope exists. It leaves all schema,
publication, operation and provider evidence intact and creates no grant. Preserve
PR85 soft unit ordering; never restore the old hard API-to-worker coupling.

For rollback, stop new delegated admission, revoke the exact grants, safely drain
or terminally block their existing reads under reviewed code, and coordinate both
runtime processes onto that compatible candidate. Never start an old schema-10
binary on the migrated ledger, drop grant/data tables, lower user_version, delete
provider messages, or relaunch a read whose outcome is uncertain.

## Verification

The complete `verify` CI job has a bounded 20-minute budget. On 19 October the Python 3.13 full suite passed 2,178 tests and 358 subtests in 13m01s, while Python 3.12 reached the former 15-minute whole-job limit after successful prerequisite checks. The budget includes clean dependencies, offline wheel verification and browser setup; no test, product timeout or other CI job limit is removed.

Synthetic coverage includes exact proof fields, current authority changes,
immutable revisions, foreign tenant/principal, unchanged list/search, generic
read denial, optional-key recovery, no-key fences, revoke/regrant, revocation
during provider read, unexpected provider identity and actual-byte SHA, and
cached-asset denial. Legacy-v1 tests also cover evidence ambiguity, origin/kind/
topic/hash mismatch, swapped renditions, revocation, and get/receipt/asset/keyed
replay across a harmless observation refresh. Live identity and byte verification are separate evidence.
