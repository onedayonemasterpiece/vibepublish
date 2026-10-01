# Telegram destination discovery

Status: `Not confirmed by user`. Owner requirement from 2026-09-29: publish to
an explicitly selected group where the connected account is a member or creator,
not only previously configured public channels. The former resolve stub was `Not done`.

`destinations.resolve` runs a read-only provider operation in the existing worker/session.
It accepts exact Telegram invite, public and private-chat links. An invite must
return ChatInviteAlready; a preview, peek, invalid invite or missing membership
never joins a group and never creates a destination. Current sending rights are
checked before returning a publish-only owner binding. This is an explicit owner
registration operation backed by provider evidence, not a grant from URL text.
Partners cannot discover or acquire destinations; revoked bindings stay revoked.
Ambiguous Telegram connections fail closed. Resolve never sends a message.

Basic-group members with current default sending permission may publish an
ordinary immediate post; other basic-group lifecycle operations remain gated.
Every actual publication retains existing native preflight, dispatch marker,
reconciliation, provider readback, and request-key idempotency. Link previews are
already disabled by the normal Telegram text adapter. No alternate account,
manual ledger surgery, joined chats, or destination-specific hardcoding is used.

## Verification and live boundary — 2026-09-29

The existing production Python environment passed 390 runtime/provider tests and
9 subtests. Regressions cover preview versus membership, malformed links,
ordinary-member permission checks, owner isolation, failed-rights no-registration,
and same-request replay without duplicate bindings.

The resolver was deployed to the server and existing worker. The newer worker's
member/native-schedule implementation and image-generation fixes were preserved.
The exact owner-supplied invite reached Telegram but did not prove existing
membership: `telegram_destination_membership_required`. The operation ended
blocked, no destination binding was created, and no message was submitted.
This is live fail-closed evidence, not successful publication acceptance.
An account actually authorized in the requested group remains necessary.

Regression tests: `tests/runtime/test_destination_resolution.py`.
