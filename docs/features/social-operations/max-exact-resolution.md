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

The primary public navigation recipe waits for the observed «Открыть в браузере» link and verifies its actual href against the exact public handle. The same page must show one visible h1 title, the exact @handle and the visible «Перейти в канал» control whose deep link matches that handle. This explicit channel control proves public channel kind without requiring a subscriber count that the current landing does not show. The older bounded native-link/subscriber recipe remains a conservative fallback. A generic Web-home/marketing link cannot select a destination. An unchanged prior native chat is refused unless its private runtime binding already contains this exact verified public URL. Oversized fallback projections, redirected public references, wrong hosts, ports, credentials, hidden controls, ambiguous identities and absent composers never persist a destination.

Private registration compares the loaded account/target document under a cooperative lock and the owned profile lease. It validates file/parent ownership and modes, uses a same-directory atomic replacement and fsync, and rolls back file plus in-memory registration if the fenced ledger transaction fails. Core rechecks owner, connection identity and active binding after provider observation. A process-crash-only orphan in the native allowlist grants no new core authorization; replay reconciles it.

## Internal verification, 2026-10-10

The scoped run passed **203 tests and 2 subtests**, including real-browser synthetic replay. The channel named-link plus photo test uses a row without the group-only outgoing flag, verifies one causal Send, early exact native-reference checkpoint, downloaded SHA evidence, fresh readback and observation-only original-attempt recovery. A deliberate post-receipt timeout preserves the original reference/quarantine and refuses a second Send; the existing group foreign-row refusal remains intact.

Immediate publication retains its existing single total driver timeout for preparation, Send and readback. This work does not introduce an effect retry or a new phase budget. The initial combined browser replay returned outcome_unknown under the fixture's 10-second budget; its underlying cause was not captured and is not asserted as a timeout. An exact diagnostic rerun passed at the same 10-second budget in 6.072 seconds, with native identity at 1.416 seconds. The final combined acceptance replay uses 30 seconds and also covers two seconds of deliberate preparation delay. Production/live acceptance remains unverified.

## Split-provider lane correction, 2026-10-10

Status: **Not confirmed by user**; live resolution remains **Not done**. The first
pilot after release c0fad40 stopped before browser navigation with
max_discovery_requires_live_connection. The ordinary Telegram/VK worker claimed
the operation as unrouted because exact discovery has no attempt or destination
binding yet. The MAX worker, which excludes unrouted operations, could not claim it.
No channel binding or publication was created.

An admitted destinations operation now carries its explicit _connection_id into
the existing Store.claim provider-lane filter. Attempt and binding routes keep
their precedence. Other action types ignore this metadata; truly unrouted work
continues to follow include_unrouted. An expired discovery lease remains assigned
to the same provider lane. This change does not open a profile, substitute an
adapter or broaden publishing rights.

Regression tests exercise the production split-worker configuration: an ordinary
lane with include_unrouted=True must leave MAX resolution accepted and untouched;
the owned MAX lane with include_unrouted=False must claim and invoke the resolver
exactly once. Tests also cover empty ordinary lanes, expired lease recovery,
unchanged attempt routes and metadata isolation for unrelated action types.
The correction's focused runtime/storage/provider suite passed **93 tests and
6 subtests**. These injected-provider tests establish routing behavior only;
a new live exact-resolution operation is still required after release.

## Observed public-link navigation correction, 2026-10-10

Status: **Not confirmed by user**; authenticated native resolution remains
**Not done**. The next production pilot reached the public landing but reported
one heading, no accepted visible Web links and no subscriber marker. This
diagnostic alone did not establish HTTP403 or a rendering cause.

The supported browser bridge and a bounded unauthenticated public HTML read
both observed HTTP200 at the exact requested URL. The visible h1 was
«Ух ты, Калининград!», with @channel_uh_kaliningrad and no visible subscriber
count. The two observed anchors were «Перейти в канал» with
max://max.ru/channel_uh_kaliningrad and «Открыть в браузере» with
https://web.max.ru/channel_uh_kaliningrad. Neither had a target attribute.
A bridge click did not produce observable navigation; navigating the actual
observed Web href returned HTTP200 and sign-in UI in that separate logged-out
profile. No authentication, native ID, membership or publishing authority was
inferred from this public inspection.

The product now waits for the actual visible controls instead of taking an
immediate DOMContentLoaded snapshot, and records the public HTTP status in
bounded diagnostics. It follows the observed href and still requires a canonical
native route, exact native header, editable composer and account reconfirmation
before registration. No successful public landing by itself creates a binding.
Browser regressions use intercepted synthetic pages for these exact SSR controls,
delayed visibility, channel-link mismatch, lack of publishing rights, HTTP403,
prior unrelated current-chat reuse and re-verification of an existing exact URL.

## Bounded preflight diagnostics, 2026-10-10

Status: **Not confirmed by user**. A production publication stopped before dispatch
with max_preflight_needs_review. That original generic receipt does not establish
which check failed. A successful earlier feed read does not prove later publish
readiness. No speculative UI fix or automatic effect retry follows from it.

The same preflight now retains a fixed-enum stage and reason in the existing
max_preflight_needs_review error message. Stages distinguish request validation,
mutation policy, and native opening. Native opening additionally identifies the
first account check, navigation, first scope check, account recheck, or final
scope check; timeout, UI assertion failure, and unavailable UI remain distinct.
Known policy/account/route blockers are whitelisted. Unrecognized reasons collapse
to an opaque blocker. No exception message, DOM, content, account identifier,
profile path, URL, credential, or asset value is exported. Live failures use the
max_web_dom evidence tag rather than offline_fixture.

Diagnostics do not change selectors, operation deadlines, driver timeout budgets,
check ordering, quarantine, dispatch, readback or retry authority. Cancellation
continues to propagate. An old terminal receipt is not retroactively diagnosed;
only a new explicitly authorized standard operation can provide fresh evidence.

The focused MAX adapter and immediate-channel browser suite passed **158 tests
and 2 subtests**. It covers all five open subphases, both timeout types, assertion
and generic failures, opaque unknown blockers, cancellation, unchanged successful
checks, no effect hooks, quarantine retention, and the existing named-link/photo
channel send and original-attempt recovery replay. A broader local browser run
reached its 240-second limit before summary and showed two failures. An isolated
existing video bridge case passed preparation but failed during execute with
max_outcome_unknown (9 preceding cases passed). Its underlying cause was not
captured and is not labeled a timeout or a baseline defect; full CI remains a
separate release gate. No live operation was run for these diagnostics.
