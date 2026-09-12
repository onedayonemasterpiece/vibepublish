# Telegram direct thread targets — P0 correction

Status: **Not confirmed by user**

## Requirement

For the owner, an exact Telegram forum-topic link is a target selector, not a
pre-registration key. Example:

`https://t.me/c/4379835477/5`

is parsed internally as chat peer `-1004379835477` plus topic root `5`. A
different `/c/<chat>/<topic>` link must derive a different peer/topic at runtime;
no specific chat number is special or hardcoded.

The owner may paste a topic link for any chat visible to the selected authenticated
Telegram MTProto account. A pre-existing VibePublish destination binding for that
chat is not required. If exactly one Telegram account connection is active, the
link is sufficient to choose the chat. If multiple Telegram account connections
are active, one existing Telegram destination alias is used only to choose the
account connection; the actual chat/topic still comes from the pasted link.

Partner/non-owner principals keep the explicit destination-binding boundary. A
URL never expands their grant.

## Runtime behavior

Owner direct links are materialized as hidden internal routing bindings so the
existing immutable plan, recovery, item-ref, history and authorization machinery
remain unchanged. Internal routes are not returned as ordinary destination aliases
and do not bump routing revision.

Provider preflight remains authoritative: the Telegram adapter must resolve the
numeric peer from the authenticated account and verify the topic/access before an
effect. A locally parsed URL is not proof that Telegram access exists.

The worker may hydrate a peer selected after worker startup by scanning the
authenticated account dialogs. Hydration is generic for the requested numeric
peer; the startup binding list is a warm cache, not an allowlist.

## Acceptance

Source acceptance requires at least two distinct `/c/<chat>/<topic>` fixtures,
owner publish/read without pre-created chat bindings, multi-account ambiguity,
partner-boundary regression, generic post-start peer hydration, `git diff --check`,
compile/import checks and the existing Telegram topic/document/readback tests.

Live acceptance remains separate on DevCoveer and must prove the same behavior
against more than one real accessible Telegram chat/topic before this status can
be promoted.
