# Exact MAX public-channel resolution

Status: **Not confirmed by user**. Implementation and offline verification do not establish live acceptance.

## Native channel feed-reference roundtrip, 2026-11-06

Status: **Not confirmed by user**. A fresh ordinary channel feed ref failed exact reading with native_reference_scope_mismatch. Failure-only live metadata confirmed that Copy returned a public-handle URL with the correct native post slug, but the existing target had no separately verified public_url; the literal URL guard correctly refused it. Feed and exact channel reads now share the existing target-correlated HistoryObserver and wire-ID conversion, including the closing fresh candidate. They retain the exact requested native ID, account/target checks, full rich content and ordered provider-media references. Empty, ambiguous or unrelated native history cannot prove that item. The test-group Copy path and strict public URL parser remain unchanged; no handle mapping is inferred or persisted. Browser roundtrip and negative history cases passed; live acceptance follows the main release.

## Tall native album read, 2026-11-06

Status: **Not confirmed by user**. A normal feed read exhausted its 90-second budget waiting for six provider images. A read-only capture proved the 1234-pixel row was visible through its caption while the entire media grid was above the viewport (bottom -19 pixels); all six native photo slots remained lazy placeholders. Scrolling the native attachment slots revealed all six actual provider image references. The existing candidate helper now scrolls its media container for media-bearing rows before the unchanged strict image/video count, provider-origin, text/entities and native-identity checks. It scrolls the row for plain text. No download, viewer opening, URL inference, added retry or budget increase is involved. A real-browser regression reproduces the offscreen placeholder grid and verifies all six ordered references, rich text, native ID and zero external effects. Live acceptance follows the main release.

## November 3 reliability correction

Status: **Not confirmed by user**. The owner superseded the historical downloaded-SHA acceptance below: MAX delivery now uses fresh native identity, text/entities, attachment count and provider references. Post-dispatch observation and finalize do not reload expired input bytes or download provider media. Stored original checkpoints remain immutable. Temporary preflight errors retain the existing worker retry codes and bounded phase diagnostics. See the [current reliability requirements](README.md#max-reliability-repair--2026-11-03).

## Owner lifecycle correction, 2026-11-03

Status: **Not done**. Each independent MAX command must automatically finish with a fresh verified native receipt or a concrete terminal delivery refusal. No terminal unknown/needs-review or manual unlock is part of normal publishing. A historic dispatch must not block another command. A delivery refusal is not evidence that a possible external effect was absent: the same attempt stays fenced against another Send/Save.

The authoritative at-most-once boundary is the existing durable worker before_effect transaction; the profile flock protects browser ownership. Remove the duplicate profile-wide uncertain marker dependency. Dispatched attempts use the existing bounded worker observation of the original immutable attempt, never another execute. Stale checkpoint/native IDs cannot fabricate success. After dispatch, temporary provider unavailability keeps the same attempt actively verifying through the existing worker lease/backoff and bounded read-only calls, including after the original mutation horizon. That horizon never authorizes another Send/Save; no external reconcile is required. Preserve historical checkpoints and marker files as evidence; do not manually unlink them.

This owner decision supersedes historical quarantine/release instructions below for the current MAX publishing path. Live acceptance remains unconfirmed.

## Daily rich editor recurrence, 2026-11-04

Status: **Not confirmed by user**. Issue 328 passed account, target and image-upload checks but rich composition failed before dispatch. Production evidence includes an incorrect link span with equal text/entity counts, then an assertion at link-dialog opening. A preparation-only reproduction captured dialog count 0 on entity 4 (offset 280, length 8), with the correct DOM range and active editor. A browser regression separately reproduces deferred focus restoration and return before the native selection event is consumed. The existing selection helper completes focus, waits for the native document selectionchange task, then retains its exact semantic range check before one keyboard action per entity. Input-element selection events cannot substitute for that document event. Strict final text/entities validation remains. The corrected preparation-only live run matched the same frozen 300 characters and all 6 entities, cleaned its own draft, and performed no Send; daily delivery still requires release and a genuine provider receipt. See the [Selection API event contract](https://w3c.github.io/selection-api/#selectionchange-event). Content-free failure diagnostics retain phase, span, dialog count and active selection; no sleeps, key retries, synthetic input events or editor internals are used.

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

## Account readiness budget correction, 2026-10-10

Status: **Not confirmed by user**. The authorized original recovery remained
not_attempted and reported open_account_before / timeout. Its validating-to-blocked
interval was 11.284 seconds; the original failure took 31.520 seconds. Production
was configured for 90 seconds. These intervals support an inner timeout mismatch
(the account checker used hardcoded 10-second settings/phone waits and default
navigation timeout), but do not identify the exact failed substep or prove that
longer readiness alone will repair the live session.

The visible-account checker now shares one monotonic configured timeout across
navigation, the existing exact Settings control's readiness/click, and the
existing visible phone field's readiness/read. Every Playwright call receives the
decreasing remainder; zero never disables a timeout. The enclosing native open
retains one total budget across both account checks and channel navigation/scope.
Publication preflight additionally caps that budget at the immutable operation
deadline. No step resets the outer budget or increases the configured maximum.

The exact observed selectors and exact account-value comparison remain mandatory.
Missing controls, a logged-out page, duplicate controls, or another account never
prove authorization. There is no alternate selector, cached identity approval,
login fallback, retry, or post-effect budget change. Diagnostics add only the fixed
navigation/settings/phone subphase to the account-before/account-after stage,
including an enclosing deadline timeout; cancellation still propagates unchanged.
Neither expected nor observed account values are exported.

Live readiness still requires a separately coordinated normal-product read using
this same checker, cold and warm. Offline tests and a successful earlier feed read
do not satisfy that gate. No publication recovery is authorized by this change.

The focused suite passed **180 tests and 2 subtests**. Real-browser tests intercept
all requests and show both a 10.1-second Settings delay and a 10.1-second phone
readiness delay succeeding within the unchanged single 20-second test budget,
followed by fresh warm checks. Logged-out pages, duplicate Settings controls and
wrong accounts fail closed. Unit tests verify strictly decreasing step remainders,
no disabled zero timeout, combined before/after account budget, immutable operation
deadline, cancellation and bounded subphase diagnostics. Existing immediate-channel
named-link/photo send and original-attempt recovery remain covered by synthetic
replay. These checks do not establish live authentication or native send readiness.

## MAX native media receipt contract, 2026-11-03

Status: **Not confirmed by user**. A live scheduled-photo receipt on release
5468176 reported provider_identity_only, but the public delivery schema omitted
that existing evidence value and rejected the whole status result. The delivery
schema accepts provider_identity_only for native identity and attachment
references without downloaded-byte verification. This does not assert source-byte
equality, change delivery state, or add downloads. Scheduled remains scheduled,
not published. The existing contract regression now validates this MAX receipt
through the normal status output schema. Live status replay follows deployment.

## Test-group scheduled cancellation title, 2026-11-03

Status: **Not confirmed by user**. Live cancellation of the owned scheduled
photo stopped before dispatch because the exact confirmation heading is
«Удалить сообщение?»; the recipe expected the same text without its question
mark. The test-group recipe uses the observed exact heading. The existing
single trusted deletion, native row guard, durable before-effect fence and
removal/readback proof are unchanged. The channel heading is unchanged.
Replay tests use the actual group title and retain one-effect and changed-row
refusal assertions. Live acceptance must cancel the same scheduled test object.

## Native attachment references in MAX reads, 2026-11-03

Status: **Not confirmed by user**. Normal exact photo and album reads omitted media
when native attachment references exist but downloaded-byte evidence does not.
MAX item/feed/queue reads must expose the observed ordered attachment slots
through the existing media/source=existing/position schema, without downloads,
new assets or a byte-equality claim. The enclosing scoped item ref identifies
the native object; role=auto does not guess a media type from a signed URL.

The projection now uses those existing slot references; the same source binding
and private native snapshot remain authoritative. The distinguishing one/two
attachment test fails without this projection; live exact reads must confirm
the observed counts after deployment.

## Normal-path rich composer mismatch diagnostics, 2026-11-03

Status: **Not confirmed by user**. Two normal issue326 attempts refused before dispatch with
max_rich_composer_mismatch, while the same frozen draft matched three live
preparations, including the actual channel. The path difference must be captured
at the existing final comparison, before teardown. Operational diagnostics may
include only lengths, entity types/UTF-16 offsets and the first differing span;
never draft text, link URLs, DOM, account data or session contents. Existing rich
validation and dispatch authority remain unchanged. Transient classification is
deferred until the actual normal-path difference is observed.

The existing refusal now emits that bounded comparison JSON in the worker
journal at the same point. It neither waits nor retries and preserves the
original MaxBlocked code; the source test ensures text/URLs cannot appear.


## Cancellation verification after causal removal, 2026-11-03

Status: **Not confirmed by user**. The live cancel persisted exactly one trusted Delete with the exact row removed, then completed a fresh scoped absence read. A duplicate identical verification pass exhausted the existing driver budget and the fixed command horizon; it did not strengthen the causal receipt. Cancellation uses the existing causal removal plus one fresh native absence read, retaining account checks before and after that read and every original binding/identity guard. Absence without the trusted removal remains insufficient. No timeout, retry, state or manual repair path is added. The original live attempt still requires genuine observation; its persisted terminal refusal is not relabelled as success.

The existing original-operation observation endpoint also accepts MAX terminal refusals whose durable dispatched attempt has no observation. It uses the same operation/attempt, frozen checkpoint, authorization and observation-only worker branch; it never re-enters Send/Delete. This preserves compatibility of the existing endpoint after MAX stopped using the terminal outcome_unknown state. It is not a new normal-flow retry or a substitute for the single-pass cancellation fix.


## Native Copy baseline after layout, 2026-11-03

Status: **Not confirmed by user**. Repeated normal photo reads failed context_menu_subject_changed. A content-free live capture showed the same connected row retained its text/entities/time while the existing scroll revealed its photo (media DOM0 to1). The existing scroll now precedes the baseline snapshot. Native reference and the complete post-scroll snapshot remain checked unchanged; no wait, retry, media download or weaker identity comparison is added.


## Immediate native confirmation after Send, 2026-11-03

Status: **Not confirmed by user**. The actual issue326 Send passed rich validation and persisted the native reference, then exhausted90seconds after its first candidate read and an18.277second repeated account check, during navigation for another read. The existing immediate path keeps the trusted single Send/new-row transition, early native checkpoint, one page reload and one final native candidate after the closing account/scope check. It removes the additional intermediate account/scope and candidate/copy pass; final native identity/media validation remains unchanged. No budget, retry or state is added. The original dispatched operation must only be observed, never republished.

## Exact native read after attachment readiness, 2026-11-03

Status: **Not confirmed by user**. A live photo read on a7377a0 still refused context_menu_subject_changed: the same connected row retained text/entities/time and one native tile, while its image hydrated from zero to one during an early Copy Link. Exact reads use the existing _plain_candidate attachment readiness before copying the native reference, then compare the requested native ID and retain the final fresh identity read. The obsolete early pre-copy and download-era comment are removed. The replay with lazy media reproduces the refusal before this deletion and passes afterward with two native copies and no effect.

## Service-owned original MAX observation, 2026-11-03

Status: **Not confirmed by user**. The eventsbot_max_digest principal has bootstrap/publish/status and its original observation was rejected HTTP422 before admission. The existing publication command endpoint permits reconcile for its own original dispatched MAX publish attempt, without publication.manage. The required operation/attempt/revision/key remain immutable; private principal ownership, current publish binding/epoch/native target and frozen plan digest remain mandatory. No caller-provided native reference, item adoption/rebase, edit/delete recovery, other provider or zero-dispatch effect is permitted through this service capability. Existing idempotency and the observation-only worker branch prevent another Send. Credentials, scopes and routes are unchanged; live original receipt remains required.
