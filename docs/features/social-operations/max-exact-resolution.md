# Exact MAX public-channel resolution

Status: **Not confirmed by user**. Implementation and offline verification do not establish live acceptance.

## Owner requirement, 2026-10-10

An owner may resolve an explicitly supplied public MAX channel URL through the existing authenticated MAX product runtime and register a stable destination. Several exact channels may coexist. Resolve never publishes, joins, subscribes, searches message history, enumerates the account, imports credentials, or guesses a native ID.

The provider must prove the exact public URL, native channel ID, title, channel kind and an available publishing composer in the same account. Ambiguous navigation, unsupported UI, non-channel targets, absent publishing rights or revoked core authority fail closed. Diagnostic evidence is bounded to visible channel/navigation structure and never includes private message content, account identifiers, credentials or application-private state.

## Authority and persistence

MAX registration is owner-only and uses one active max_web connection. Existing destination aliases are retained, request replay is idempotent, revoked bindings are not restored and unrelated rights are not expanded. A newly verified channel receives only publish in the core ledger. Its exact native target is saved atomically to the existing private runtime allowlist with the explicit publish_channel policy. Existing test_group and scheduled_only policies remain unchanged, including when the exact URL resolves to an existing target: that case returns an explicit policy conflict rather than silently upgrading or replacing its policy.

A publish_channel permits immediate channel publication through the existing preflight, durable dispatch, native identity/readback and outcome-unknown safeguards. It does not grant arbitrary lifecycle actions. Channel-owned posts must use channel row semantics even when MAX does not mark them as account-outgoing. Every actual send still rechecks account, native route, exact title, composer and immutable plan.

## Acceptance boundary

Required offline checks cover strict URL parsing, ambiguity, wrong target type, absent rights, replay, existing aliases, revocation, private atomic allowlist updates and immediate-channel policy isolation. Live exact resolution and live publication/readback are separate evidence gates; no test may post to a real channel.

The public navigation recipe follows a unique visible MAX Web link observed on the exact public landing. The link must encode an observed native route or the same public reference; a generic Web-home/marketing link cannot select the previously opened chat. Public subscriber text must be visible. Oversized heading/link projections fail closed rather than silently hide ambiguity. Redirected public references, wrong hosts, ports, credentials, hidden links, native route substitution and absent composers never persist a destination.

Private registration compares the loaded account/target document under a cooperative lock and the owned profile lease. It validates file/parent ownership and modes, uses a same-directory atomic replacement and fsync, and rolls back file plus in-memory registration if the fenced ledger transaction fails. Core rechecks owner, connection identity and active binding after provider observation. A process-crash-only orphan in the native allowlist grants no new core authorization; replay reconciles it.

## Internal verification, 2026-10-10

The scoped run passed **203 tests and 2 subtests**, including real-browser synthetic replay. The channel named-link plus photo test uses a row without the group-only outgoing flag, verifies one causal Send, early exact native-reference checkpoint, downloaded SHA evidence, fresh readback and observation-only original-attempt recovery. A deliberate post-receipt timeout preserves the original reference/quarantine and refuses a second Send; the existing group foreign-row refusal remains intact.

Immediate publication retains its existing single total driver timeout for preparation, Send and readback. This work does not introduce an effect retry or a new phase budget. The initial combined browser replay returned outcome_unknown under the fixture's 10-second budget; its underlying cause was not captured and is not asserted as a timeout. An exact diagnostic rerun passed at the same 10-second budget in 6.072 seconds, with native identity at 1.416 seconds. The final combined acceptance replay uses 30 seconds and also covers two seconds of deliberate preparation delay. Production/live acceptance remains unverified.
