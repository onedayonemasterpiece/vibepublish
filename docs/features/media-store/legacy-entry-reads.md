# Exact legacy-entry reads

Requirements: `Fixed` for the owner's four canonical Regional Knowledge archive
originals. Implementation: `Not confirmed by user`. The legacy ownership mismatch
is `Not done` until the reviewed release and exact live byte readbacks complete.
Source/test preparation is not runtime acceptance.

## Boundary

This is a read-only exception for an already existing technical principal, not
publication reassignment or a new sharing surface. No credentials, owner scope,
binding, provider message, document clone, service, or queue is created.
List/search keep their existing publication-principal boundary. The service
cannot use generic item reads to bypass its narrow media-store tool scope.

The private operator manifest contains exactly the four approved canonical entry
identities, not a duplicate, with verified source origins and SHA-256 values.
The manifest is not committed. Public fixtures are synthetic.

## Durable authorization

Schema 11 adds exact grant records and temporary-asset-to-grant links.
A grant contains a frozen proof of the current target tenant/principal and epoch,
binding ID/epoch, connection and destination, source publication owner/revision,
Telegram chat/topic/message/attachment identity and immutable origin including SHA.
A grant never derives authority from an origin URI or Telegram link alone.

Get admission checks current proof before keyed replay or fresh admission.
The existing durable operation stores the immutable grant ID, including no-key
reads. Status, replay, the worker before provider access and after download, and
each byte-cache read revalidate that same grant. Revocation deletes the grant;
regrant creates a different ID and cannot revive an old operation or cache.

The worker accepts exactly one source document at the exact native identity and
topic, and hashes actual downloaded bytes against the immutable origin SHA.
Unexpected/extra documents, changed source revisions, revoked topic/binding,
foreign tenant/principal and mismatched bytes fail closed before cache insertion.
The existing one-hour cache remains temporary. No document is republished.

## Migration and release gate

This change is not compatible with an API-only rollout. Old workers do not know
the grant guard and old Store initialization rejects schema 11. Do not initialize
the new Store on the live ledger, admit shared reads or apply grants until:

1. The exact candidate and schema-11-compatible rollback source pass review and
   required checks.
2. The actual systemd unit dependency/restart coupling is understood. Obtain a
   coordinated idle/drain window without interrupting unrelated active commands.
3. Both server and worker actual PIDs, command lines and immutable release roots
   prove the reviewed candidate is loaded, not merely configured. Preserve active
   ledger operations and existing provider session exclusivity.
4. Perform the migration only in that coordinated window; verify integrity and
   preserved operation/publication identities before any grant.
5. Verify the existing service is non-owner with exactly its original narrow
   scopes and binding. Recheck all four frozen proofs transactionally, refuse
   unexpected existing entry grants, and apply only the reviewed exact set.
6. Read each canonical source through the existing service identity, await its
   original operation, then verify the actual asset SHA. Verify denied foreign
   entry/topic/tenant/principal and revoked-grant cases with synthetic fixtures.

Runtime work remains on hold while the separate release incident is unresolved.

## Recovery without schema downgrade

Before live migration, prepare and test a stable-PR83 rollback candidate which
accepts the additive schema 11 but denies grant-marked read operations at both
worker and private-status boundaries. It must also deny every foreign-source
download cache even if an unrelated publish scope exists. It leaves all schema,
publication, operation and provider evidence intact and creates no grant.

For rollback, stop new delegated admission, revoke the exact grants, safely drain
or terminally block their existing reads under reviewed code, and coordinate both
runtime processes onto that compatible candidate. Never start an old schema-10
binary on the migrated ledger, drop grant/data tables, lower user_version, delete
provider messages, or relaunch a read whose outcome is uncertain.

## Verification

Synthetic coverage includes exact proof fields, current authority changes,
immutable revisions, foreign tenant/principal, unchanged list/search, generic
read denial, optional-key recovery, no-key fences, revoke/regrant, revocation
during provider read, unexpected provider identity and actual-byte SHA, and
cached-asset denial. Live identity and byte verification are separate evidence.
