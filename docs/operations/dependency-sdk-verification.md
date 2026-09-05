# Dependency and Telegram SDK qualification

Status: **Not confirmed by user**. This is an independent source/tooling package,
not delivery of the protected core tree. PR #1 still lacks the full runtime.
No model, Telegram RPC, credentials, MAX changes or deployment are involved.

## What the gate proves

The existing GitHub-hosted CI qualifies the direct pins in `requirements.in`
plus explicit test dependencies in `requirements.verification.in`, on Python 3.12
and 3.13. It resolves them in an empty venv, records the exact dependency graph,
builds a wheelhouse, hashes each wheel, and installs that exact wheelhouse into
another empty venv with `--no-index --require-hashes`. Both environments run
`pip check` and exact installed-version checks. No system packages are reused.
The initial qualification resolves a graph; it is not yet a committed universal
lock. `artifacts/verification/resolved.lock` is the candidate to inspect and pin.
`wheelhouse.lock` hashes apply to those exact wheels, not arbitrary PyPI builds.

`scripts/verify/dependencies.py` rejects ranges, duplicates, missing/unexpected
wheels and installed packages/version drift. Packaging regression tests cover
these checks; failures are not converted to skipped tests or relaxed versions.

`scripts/verify/telegram_wire.py` requires actual Telethon 1.44.0 and serializes
and deserializes the 14 native request constructors needed by the adapter. Three
custom entities have distinct literal IDs and variable UTF-16 spans. Text/media/
album/edit/native schedule/forward/read/cancel/delete requests use real TL types.
No TelegramClient is created; an audit hook forbids attempted socket connections.
This evidence is **real SDK only**, not transport/core/live acceptance.
`--core` additionally requires the actual VibePublish compiler, checks all its
RPC mappings and native entity conversion; absent core fails in that mode.

## Reproduce

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.verification.in
.venv/bin/python -m pip check
.venv/bin/python scripts/verify/telegram_wire.py
.venv/bin/python -m pytest tests/verification -q
```

For a complete locally restored runtime, install the application separately and
run `python scripts/verify/telegram_wire.py --core`, then the full tests. The old
seed's pyproject is not a substitute for that package or its dependency metadata.
CI currently runs only delivered contract/inventory/tooling code; successful
SDK and environment gates cannot be presented as remote full-runtime CI.

## Observed local network failure, 2026-09-05

The repeated local attempt to install the original lock failed on DNS resolution
for PyPI before obtaining package versions. This does **not** prove that
annotated-types 0.8.0 does not exist. Its official PyPI release metadata and
Telethon 1.44.0 metadata were read. Do not downgrade these pins to mask DNS errors.
No full-core write has been retried or routed through CI; only this new,
independently useful dependency/SDK qualification code is delivered here.

Primary metadata:
- https://pypi.org/project/annotated-types/0.8.0/
- https://pypi.org/project/Telethon/1.44.0/
- https://pypi.org/project/mcp/1.29.0/
