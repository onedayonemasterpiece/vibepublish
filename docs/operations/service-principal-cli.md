# Scoped service-principal CLI

Status: **Not confirmed by user**. This is the canonical local-administration
contract for explicit principal scopes and destination binding rights. Runtime
provisioning and credential handling require separate owner authorization.

## Explicit authority selection

The owner-only `principal` command accepts repeated `--scope` flags. When any
flag is supplied, the stored scope set is exactly that selection, with duplicates
removed. It does not add the legacy partner defaults. A service that only needs
bootstrap, publishing and status uses:

```text
principal --tenant TENANT --principal PRINCIPAL \
  --scope bootstrap --scope publish --scope status
```

The owner-only `bind` command accepts repeated `--right` flags with the same
replacement semantics. Use `--right publish` for a publish-only binding to one
explicit native destination. Each later destination needs its own authorized
binding; no wildcard, URL-based grant or implicit discovery is introduced.

```text
bind --principal PRINCIPAL --alias DESTINATION_ALIAS \
  --connection CONNECTION --native-id NATIVE_ID --label LABEL --right publish
```

These are command fragments for `python -m social_operations.cli --db DATABASE`,
not an instruction to provision an identity. Service credentials stay in the
existing private operator flow and must not be pasted into chat or committed.

## Validation and compatibility

The CLI accepts only current storage-defined scope and right names. Unknown,
empty or missing flag values fail during argument parsing before opening the
database or requesting owner authentication. Storage independently rejects
unknown names and malformed authority collections before generating credentials,
opening a mutation transaction, or changing bindings. Duplicate valid selections
are normalized. An empty collection in the storage API still represents no
authority for existing callers; the CLI cannot use an empty flag to select it.

Omitting `--scope` preserves the existing partner defaults: `bootstrap`,
`publish`, `publication.manage`, `visual`, `status`, `forward`, and
`destination.profile`. Omitting `--right` preserves existing binding defaults:
`publish`, `edit`, `reschedule`, `cancel`, `delete`, and `forward`.
The existing `grant-rights` command remains additive and requires at least one
valid right; it uses the same right-name registry.

These flags do not create new scopes, independent source-reading authority,
owner privileges, credential transport, or provider capabilities. The existing
[partner read contract](../features/social-operations/README.md#owner-correction-reading-follows-publishing-destinations)
continues to derive channel reads from active publishing destinations. Publish
scope retains its existing private asset upload/read access; unrelated
management, visuals and engagement scopes are not silently added.

## Bound destination identity

Bootstrap and destination listings expose the existing concrete binding's
`alias`, `provider`, `native_id` and binding-epoch `revision`. The optional
`native_id` field is provider-native data for an already authorized destination;
it grants no access and is never emitted for a destination set. Service clients
can verify this tuple against their configured target before publication.

## Authenticated owner edit grant

Status: **Not confirmed by user**. The authenticated MCP
`vibepublish_destinations` command `binding_grant_edit` adds exactly the
`edit` right to one existing, active binding owned by the current principal.
It requires current owner authority and both existing `destinations` and
`publication.manage` scopes. The branch is absent from schemas projected for
nonowners or callers missing either scope; admission independently rechecks
current persisted authority rather than trusting a stale actor snapshot.

```json
{
  "command": {
    "kind": "binding_grant_edit",
    "alias": "existing_alias",
    "expected_binding_epoch": 1,
    "expected_routing_revision": 3
  },
  "request_key": "grant-edit-existing-alias-once"
}
```

Use the concrete binding's bootstrap/list `revision` as
`expected_binding_epoch` and bootstrap `routing_revision` as
`expected_routing_revision`. Destination sets, other principals or tenants,
unknown aliases, caller-supplied rights/scopes, and arbitrary target identifiers
are rejected. The command does not create credentials, new identities, scopes,
bindings, or provider effects and does not clear quarantine or rewrite epochs.

The existing additive CLI grant domain is reused within one transaction:
exact CAS, rights update, routing revision, completed operation/event and
request-key mapping commit or roll back together. Routing increments once when
`edit` is newly added and stays unchanged if already held. The receipt's
`binding_grant` records binding ID, alias, the fixed `edit` right, and
`before`/`after` snapshots of rights, binding epoch, actor epoch and routing
revision. A matching key returns the original receipt before stale CAS is
evaluated and never reapplies a grant. Current authority and exact active
binding/epoch/edit access are checked again for replay and status; revocation
cannot be undone with an old key. A different request using that key conflicts.

The legacy owner CLI `grant-rights` retains its explicit same-tenant
administration scope and additive right registry. The narrower MCP command
adds no CLI scope requirement. Neither route can trust a forged or stale
`owner` flag in place of current persisted owner authority.

## Offline verification

`tests/runtime/test_cli_authority.py` checks explicit replacement, duplicate
normalization, legacy defaults, CLI rejection before store access, storage
rejection before effects, safe empty authority, and exact MAX URL-only resolve
schema compatibility. Its CLI/store guards use offline stubs and perform no live
principal, grant or provider changes.

`tests/runtime/test_owner_binding_edit_grant.py` covers owner/scopes and forged
actor checks, exact principal/tenant/alias boundaries, both CAS values, atomic
rollback, one-time routing changes, keyed replay, revocation, hidden schemas and
rejection of arbitrary rights or scopes using isolated offline databases.
