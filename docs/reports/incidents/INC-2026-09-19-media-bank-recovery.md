# INC-2026-09-19-media-bank-recovery

Status: `Not confirmed by user` — recovery and list fix verified through live MCP

## Summary

Owner reported an empty media bank after the DevCoveer crash, then confirmed the
Telegram thread was readable but `media_store.list` returned `access_denied`.
The owner named https://t.me/c/4379835477/5 as the recovery source.

## Impact

Before repair, the active index had no media-store publications. After recovery,
`list` still required a hidden direct-route alias and metadata-only thread reads
could erase verified hashes, causing output validation to fail.

## Root Cause

Historical ledger data was missing in the active recovery database. The exact
loss mechanism is unproven; intact Telegram documents remain authoritative.
Separately, the list contract redundantly required a hidden alias, and fact
upserts replaced byte evidence with metadata-only observations.

## Fix

Recovered 106 entries / 147 image documents (128 distinct SHA-256 values,
227,181,014 bytes) from topic 5. Original captions, album membership and native
message links are retained. A consistent pre-change SQLite backup was made;
all index changes were committed in one transaction under the current owner.
Replay created zero duplicates. No Telegram publication or deletion was performed.

Enabled the existing Wonderful Lections asset bridge via a systemd user drop-in,
scoped only to tenant_owner and the existing private VibePublish token file.

Contract 1.6.2 makes `to` optional for list. The exact thread URL still resolves
only an existing active owner binding; an explicit mismatched alias returns
`media_store_destination_mismatch` with `fix_input`. Metadata-only reads preserve
hash evidence only when ordered provider media and album member IDs are unchanged.

## Regression Checks

- All 147 documents downloaded, decoded and hashed; coverage matches inventory.
- SQLite integrity and foreign keys pass; 106 media-store publications.
- Idempotent restore replay: zero added rows.
- Forty focused tests and 204 schema subtests pass.
- Public MCP search for Яндекс returns indexed entries.
- Native get of message 218 and album 38–40 completes as verified; all four
  asset endpoint downloads match independently captured SHA-256 values.
- Existing Wonderful Lections deployment-smoke presentation
  `pres_6af859d86f2f45ce8c80e2ec552f98ef` received message 218 via connector_ref,
  revision 3. Original readback matches source SHA-256
  `58ed8f24f12138ed01e718094248ecc6ca273edd6dfcb0cdfcc8422f9997c3dc`.
- Live MCP list without `to` returns 50 items with `truncated=true` and no empty
  hashes. A verified 20-item provider thread refresh followed by the same list
  retains all hashes. The database contains 106 indexed entries with zero empty
  hashes and passes integrity checks.
- An explicit stale alias now returns `media_store_destination_mismatch` and
  `next_action=fix_input`, rather than `access_denied`.
- Runtime services remain active with zero restarts. End-user client acceptance
  is pending.

## Release Evidence

Retained recovery evidence:
`/home/dev/artifacts/vibepublish/20260919T074931Z-media-bank-recovery-20260919`.

Retained list-fix evidence:
`/home/dev/artifacts/vibepublish/20260919T085554Z-media-store-list-access`.

## Follow-Ups

Use normal media_store search/get and presentations.assets.add for the target
lecture. The restored bank preserves repeated source files rather than silently
dropping original messages. The exact historical cause of data loss remains
unproven; this recovery does not claim to restore absent lectures or other topics.

## Follow-up: media_store list alias routing

Reproduced: list with the restored hidden destination alias passed routing, while
the old sample alias pka_tg or a public-channel alias failed access_denied. Omitting
to failed schema validation. Ingress deliberately hides direct-route aliases from
bootstrap destinations. Thus the required alias makes this local read difficult
to discover even though exact thread_ref already resolves the owner's binding.

Requirement correction: list requires the exact thread_ref and resolves only
existing active bindings. The redundant to field becomes optional; when supplied,
it must still match the resolved destination. This creates no grants and performs
no provider I/O. Incorrect explicit aliases receive a fix_input error rather than
an authorization diagnosis. Non-owner and revoked/unbound access stays denied.

A second regression was reproduced: worker.save_fact replaced byte-verified media
snapshots with metadata-only thread observations, erasing hashes. The list output
schema required at least one hash and then raised ValidationError. Preserve prior
byte evidence only for unchanged provider attachment identities; accept explicitly
empty hash lists after a genuine media replacement until fresh get verification.
Damaged evidence was restored from retained capture after matching provider IDs.
The live post-fix refresh confirmed that it remains intact.
