# Production runtime

## DevCoveer2 provider recovery — 2026-09-19

Status: `Not done`. Public MCP is reachable, but providerless worker startup is
not Telegram/VK/MAX acceptance. Track the missing dedicated Telegram session in
[the recovery incident](../reports/incidents/INC-2026-09-19-telegram-recovery.md).

`deploy/devcoveer/telegram_login.py` explicitly authorizes a fresh dedicated
Telegram session using an owner-scanned QR. It reads only API ID/hash from the
selected env, never other products' sessions. Install `qrcode` for this optional
operator helper. Pass private output, QR and optional two-factor-password paths;
QR artifacts must be mode 0600 inside a managed artifact directory. The output
env contains `VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE` and refuses overwrite. Login alone
does not register a connection or start a native worker. Activate native wiring
only after authorization and retain exclusive session ownership.

As of 2026-09-13, VibePublish production is expected to run from immutable releases under `/home/dev/.local/share/vibepublish/releases/<sha>` with `/home/dev/.local/share/vibepublish/current` pointing at the deployed release.

The permanent Python runtime is `/home/dev/.local/share/vibepublish/venv/bin/python`. Production server and worker units must use that interpreter, not an acceptance-project virtualenv, with `PYTHONPATH=/home/dev/.local/share/vibepublish/current`.

Trusted browser artifacts are imported only from the configured root `/var/lib/my-browser-bridge/data/artifacts` via `VIBEPUBLISH_BROWSER_ARTIFACT_ROOT`; VibePublish does not refetch source images for `import_browser_artifact`.

MAX Web passive queue/history decoding in `adapters/max/wire.py` is a production runtime path and therefore requires the direct pinned dependencies `msgpack==1.2.2` and `lz4==4.4.5`. They belong in both the canonical direct dependency graph and `requirements.lock`; an acceptance virtualenv must not be relied on to supply them.

After changing the permanent runtime, acceptance is read-only unless a write is explicitly required: verify the known Telegram topic, the bound VK destination and the bound MAX destination. MAX sanity checks must reuse the existing authorized profile and must not create a new authorization or rotate tokens.
