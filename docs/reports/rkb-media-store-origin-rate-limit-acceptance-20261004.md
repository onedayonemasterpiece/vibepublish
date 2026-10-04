# Regional Knowledge private media mirror prerequisite — 2026-10-04

The private media store accepts immutable origin metadata and shares a durable
20-files/rolling-60-seconds connection budget with ordinary Telegram publication.
Regional Knowledge image identity is its illustration resource and stable request
key. Following the owner's correction, optional source-image SHA is metadata;
there is no requirement to compare a canonical crop to a compressed/sanitized
VibePublish rendition. No perceptual matching step blocks media delivery.
VibePublish retains its existing transport evidence for the actual uploaded asset.

## Durable provider budget

Schema 7 adds the small `telegram_media_admissions` journal. While holding the
existing cross-process connection lane, the worker reserves each media batch
before entering the adapter and therefore before upload. Failed/interrupted
pre-dispatch uploads conservatively consume the window. Unknown native effects
remain observation-only. Albums count files, text-only/native forwards consume
zero, and separate connections have independent windows. Capacity defers the
same undispatched attempt, retains staging/request identity and releases the
lane; restart cannot reset the budget. Deferred media retains a delivery lifetime
through its due capacity timestamp. FloodWait/SlowMode remain independent.

Deterministic acceptance exercised 27 closely queued files across media-store
and ordinary publication, two workers, restart, eventual delivery, independent
connection and unthrottled text. Rolling windows contained at most 20 admitted
files; replay generated no effects. Additional failed-upload cases proved that
pre-dispatch media consumes budget across restart. No real bulk Telegram spam
was used for the rate test.

## Real private canary

One clearly marked synthetic image was imported through authenticated binary
asset ingress and stored as DOCUMENT in the owner's requested private topic.
Put completed in 2.343 seconds. Native DOCUMENT/topic readback passed; list,
search and get round-tripped origin. The request carried no origin SHA. Exact
request replay returned the same operation/entry and created zero additional
Telegram documents; changed origin under the same key conflicted. No public
publication was made. Temporary acceptance OAuth family was revoked.

## Regression and immutable delivery evidence

Focused media-store/budget tests passed. Local regression excluding browser
fixtures passed 912 tests and 219 subtests; version-7 migration and current skill
expectations were updated. A prior full host run was interrupted after four MAX
browser fixture failures and 316 passes; it is not recorded as a full pass.
MAX adapter/browser source was unchanged. Full remote verification and the final
canonical main/server/worker SHA are captured in the PR's final delivery receipt.

Private canary identity, queue journal timestamps, receipts and source/runtime
verification are retained under
`/home/dev/artifacts/vibepublish/20261004T114647Z-rkb-media-budget-20261004`.
The public repository contains no provider credentials, image bytes or private
source material. This prerequisite does not yet constitute Regional Knowledge
book-illustration production acceptance.
