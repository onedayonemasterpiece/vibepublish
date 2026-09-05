# Dependency and Telegram SDK verification

Status: **Not confirmed by user**. This gate verifies dependencies and native SDK
compatibility, not live Telegram acceptance or full core delivery to GitHub.
No credentials, model calls, provider RPCs, MAX changes or deployment are needed.

## One pinned environment

`requirements.lock` is the exact 70-package Linux CPython 3.12/3.13 verification
environment. It includes runtime, optional Telegram/VK SDKs, browser and build/test
dependencies; this is not a minimal production image. The direct requirements
remain in `requirements.verification.in` including `requirements.in`.

The graph was qualified in GitHub-hosted run **33953694373**, HEAD `ce3856db`, on
Python 3.12.14 and 3.13.15. Both jobs succeeded: empty virtualenv installation,
`pip check`, 14+8 contract checks, 31 inventory/tooling tests, 14 real Telegram
request roundtrips, then exact hashed offline reinstallation in a second empty
virtualenv. Ordinary CI now installs the committed lock, not newly resolved
versions. Six further regression cases cover direct-input drift/include handling.

Compared with the earlier archived 55-pin graph, all direct runtime pins stay the
same; two transitive SVG dependencies are refreshed to the qualified versions:
`cssselect2` 0.9.0 -> 0.10.1 and `webencodings` 0.5.1 -> 0.6.1. The other 15 entries
pin optional SDK/browser/build dependencies. Full local compositor/emoji/runtime
regression in this environment passed: **327 tests + 199 subtests**, no skips.

The single existing workflow builds a wheelhouse, hashes every exact wheel and
installs it with `--no-index --only-binary=:all: --require-hashes`. Wheel hashes
are specific to those artifacts/platforms, not universal PyPI source hashes.
The first online installation does not claim hash-enforced supply-chain locking.
`scripts/verify/dependencies.py` rejects package/version drift, ranges, duplicate
pins, missing/unexpected wheels and changed direct pins. `pip check` separately
checks installed dependency consistency. Public package-index access is needed
for the initial installation; wheelhouse reinstallation needs no network.

## Actual Telegram TL, not name-shaped mocks

`scripts/verify/telegram_wire.py` requires Telethon 1.44.0. It roundtrips all
14 native request types and three distinct custom emoji IDs with UTF-16 spans
2/7/4. Text, photo, album, edit, native schedule, forward, reads, cancel and delete
use real SDK objects. No TelegramClient is created; a socket audit guard forbids
network. `--core` additionally verifies the actual VibePublish compiler and every
RPC mapping, and fails when that core is absent.

The prior local `scripts/verify/telegram_sdk.py` incorrectly required requests to
exceed 8 bytes. A valid GetAppConfigRequest is exactly 8 bytes. The local full-core
entrypoint now delegates to the complete native roundtrip gate. Its **19 new SDK
tests** also exercise production adapter prepare/execute/reconcile with real TL
resolution and binary responses from an explicitly offline provider-state double:
text/photo/album, exact entities, edit/reschedule/cancel, media preservation,
wrong-ID readback, marker refusal and read-only recovery. They are not live RPCs.
These core-dependent files remain in the local full-source package, not this
seed branch. A successful remote dependency/SDK CI is not full-runtime CI.

## Reproduce

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip check
.venv/bin/python scripts/verify/dependencies.py requirements.lock
.venv/bin/python scripts/verify/dependencies.py requirements.lock --inputs requirements.verification.in
.venv/bin/python scripts/verify/telegram_wire.py
.venv/bin/python -m pytest tests/verification tests/inspection -q
```

For the complete local source, additionally install the app with `--no-deps
--no-build-isolation`, run `python scripts/verify/telegram_sdk.py` and the full
suite. No absent SDK test may be hidden with importorskip. The local full-core
workflow retains mandatory full-runtime/browser/SDK steps in the same CI path.

## Corrected diagnosis and remaining boundary

The earlier local pip failure was DNS resolution for PyPI, not proof that
annotated-types 0.8.0 does not exist. Actual official wheels now installed that
version successfully. Initial failures are retained in transfer-package logs.
The full protected core upload was not retried/routed through CI or MAX. Only
new independent dependency/SDK tooling and its qualification results are remote.
DevCoveer imagegen activation and live provider/deployment gates remain separate.
