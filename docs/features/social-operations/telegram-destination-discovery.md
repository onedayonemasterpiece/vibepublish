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
Ambiguous ordinary Telegram account connections fail closed. When one ordinary connected MTProto account and the dedicated `VIBEPUBLISH_KNOWLEDGE_BASE_AUTH_BUNDLE` connection coexist, owner exact `destinations.resolve` selects that single ordinary account, just as owner direct-link routing does. It never routes external publications through the knowledge-base lane, silently chooses between multiple ordinary accounts, or bypasses native membership/publish-rights checks. Resolve never sends a message.

Basic-group members with current default sending permission may publish an
ordinary immediate post. Provider-native scheduled publish remains gated by
default and is enabled only when the owner explicitly adds the additive
`basic_group_schedule` right to that exact binding. The right is not part of
default bind/resolve rights, is frozen into the immutable attempt plan, and is
revalidated immediately before provider effect. A scheduled basic-group request
without that trusted plan authorization remains
`telegram_group_mutations_needs_review`.

Edit/reschedule/cancel/delete/forward remain separately gated by their existing
provider/lifecycle contracts. Every actual publication retains native preflight,
dispatch marker, reconciliation, provider readback, and request-key idempotency.
Link previews are already disabled by the normal Telegram text adapter. No
alternate account, manual ledger surgery, joined chats, or native-target
hardcoding is used.

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

Regression tests: `tests/runtime/test_destination_resolution.py`,
`tests/providers/test_basic_chat_creator.py`,
`tests/runtime/test_service.py`, and `tests/runtime/test_engagement.py`.
