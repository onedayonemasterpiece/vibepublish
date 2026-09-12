# Telegram direct link targets — P0 correction

Status: **Not confirmed by user**

## Requirement

For the owner, an exact Telegram message/topic permalink is a target selector,
not a pre-registration key. No concrete Telegram peer such as
`-1004379835477` is special or hardcoded.

Supported owner selectors in this P0 are exact message/topic permalinks parsed by
the canonical Telegram URL parser, including:

- private/supergroup form: `https://t.me/c/<chat>/<message-or-topic>`;
- public username form: `https://t.me/<username>/<message-or-topic>`;
- public preview form: `https://t.me/s/<username>/<message-or-topic>`.

The owner may paste such a link for any chat visible to the selected authenticated
Telegram MTProto account. A pre-existing VibePublish destination binding for that
chat is not required. If exactly one Telegram account connection is active, the
link is sufficient. If multiple Telegram account connections are active, one
existing Telegram destination alias selects only the account connection; the
actual chat/topic still comes from the pasted link.

Partner/non-owner principals keep the explicit destination-binding boundary. A
URL never expands their grant.

## Runtime behavior

Owner direct links are materialized as hidden internal routing bindings so the
existing immutable plan, recovery, item-ref, history and authorization machinery
remain unchanged. Internal routes are not returned as ordinary destination aliases
and do not bump routing revision.

The direct Telegram adapter resolves a public username through the authenticated
account before any provider effect and converts it to the actual numeric peer for
all native RPCs. The caller-facing route stays stable, while the provider numeric
peer is written into the existing durable Telegram checkpoint before mutation.
If recovery runs after a possible effect, it uses that numeric checkpoint and does
not trust or re-resolve a mutable public username.

The referenced Telegram message is also inspected before an effect. For a forum
chat, a topic-root link targets that topic and a message inside a topic resolves to
its actual topic root. For an ordinary non-forum chat/channel, the same permalink
selects the chat root rather than fabricating a forum topic.

Provider preflight remains authoritative: URL parsing alone is never proof that
the authenticated account can see or publish to the target.

Numeric peers selected after worker startup may be hydrated from authenticated
account dialogs. The startup binding list is a warm cache, not an allowlist.

## Acceptance

Source acceptance covers multiple unrelated `/c/...` peers, public username
permalinks, forum-topic and ordinary-chat interpretation, owner publish/read
without pre-created chat bindings, multi-account ambiguity, partner boundary,
post-start peer hydration, recovery from the durable numeric checkpoint,
`git diff --check`, compile/import and existing document/media readback tests.

Live acceptance remains separate on DevCoveer and must prove the behavior against
more than one real accessible Telegram chat/topic before this status can be
promoted.
