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

## Offline verification

`tests/runtime/test_cli_authority.py` checks explicit replacement, duplicate
normalization, legacy defaults, CLI rejection before store access, storage
rejection before effects, safe empty authority, and exact MAX URL-only resolve
schema compatibility. Its CLI/store guards use offline stubs and perform no live
principal, grant or provider changes.
