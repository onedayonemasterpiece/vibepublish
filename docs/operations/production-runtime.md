# Production runtime

## DevCoveer2 provider recovery — 2026-09-19

Status: Telegram and VK reads `Not confirmed by user` (public MCP reads verified);
MAX recovery `Not done`. Public MCP availability alone is not provider
acceptance. Track provider wiring and verification in
[the recovery incident](../reports/incidents/INC-2026-09-19-telegram-recovery.md).

Recovery must use the existing owner-designated Telegram session from `.env`
through Telethon `StringSession`. Resolve the credential mapping before changing
the runtime; an unexpected variable name does not establish a missing session.
Do not initiate new authorization, generate login challenges, or create, replace
or rotate sessions without the owner's explicit permission. Retain exclusive
session ownership. Acceptance requires a real provider-backed read, not merely
an active service or successful health response.

The owner-designated source is `/home/dev/.env:TELEGRAM_VIBE_PUBLISH`, a
base64-encoded JSON bundle containing a Telethon session. API credentials come
from `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in the same file. The production
worker supports explicit `--telegram-session-key`, `--telegram-api-id-key` and
`--telegram-api-hash-key` arguments; it maps only these selected credentials to
the in-memory `VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE` reference. No secret copy or
fallback to another session is required. `--telegram-only` explicitly permits
the single-provider recovery topology and rejects other active connections;
the default full-provider topology remains strict. The session lock remains
mandatory in both modes.

For incremental recovery, `--providers telegram vk` explicitly selects those
two providers without requiring a MAX profile. Omitting provider selection still
requires all three. It is mutually exclusive with legacy `--telegram-only`;
missing, duplicate or extra active connections fail closed. VK requires an
explicit existing `--vk-env-file` and `--vk-token-key`; no token guessing or
fallback is performed. This capability is not evidence of VK connectivity:
[VK recovery acceptance](../reports/incidents/INC-2026-09-19-vk-recovery.md)
records the completed provider-backed read acceptance separately from publication
acceptance. On this host VK uses `/home/dev/.env:VK_USER_TOKEN1`, selected after
read-only verification against the historically used account and `lovekenig`
group. `VK_USER_TOKEN2` also passed those checks but is not an automatic fallback.

The DevCoveer2 `vibepublish-worker.service` runs the existing production worker
with the following arguments (paths and variable names only, never secrets):

```text
--db /home/dev/.local/state/vibepublish/vibepublish.sqlite3
--telegram-env-file /home/dev/.env
--telegram-session-key TELEGRAM_VIBE_PUBLISH
--telegram-api-id-key TELEGRAM_API_ID
--telegram-api-hash-key TELEGRAM_API_HASH
--providers telegram vk
--vk-env-file /home/dev/.env
--vk-token-key VK_USER_TOKEN1
```

Current recovery deployment uses `/home/dev/projects/vibepublish` and interpreter
`/home/dev/.local/opt/vibepublish/bin/python`; migration to the historical immutable
release layout below has not been performed by this provider repair.

VK shared-post reads resolve the requested wall's ID only when the provider
returns both an exact `coowners.coowner_post_id` and a matching approved list
entry. Feed and exact-item reads use that wall-local ID. Unknown, conflicting,
pending, and scheduled cross-wall mappings fail closed; the general target
identity check remains intact. This behavior was verified against actual
`wall.get` and `wall.getById` responses on DevCoveer2.

As of 2026-09-13, VibePublish production is expected to run from immutable releases under `/home/dev/.local/share/vibepublish/releases/<sha>` with `/home/dev/.local/share/vibepublish/current` pointing at the deployed release.

The permanent Python runtime is `/home/dev/.local/share/vibepublish/venv/bin/python`. Production server and worker units must use that interpreter, not an acceptance-project virtualenv, with `PYTHONPATH=/home/dev/.local/share/vibepublish/current`.

Trusted browser artifacts are imported only from the configured root `/var/lib/my-browser-bridge/data/artifacts` via `VIBEPUBLISH_BROWSER_ARTIFACT_ROOT`; VibePublish does not refetch source images for `import_browser_artifact`.

MAX Web passive queue/history decoding in `adapters/max/wire.py` is a production runtime path and therefore requires the direct pinned dependencies `msgpack==1.2.2` and `lz4==4.4.5`. They belong in both the canonical direct dependency graph and `requirements.lock`; an acceptance virtualenv must not be relied on to supply them.

After changing the permanent runtime, acceptance is read-only unless a write is explicitly required: verify the known Telegram topic, the bound VK destination and the bound MAX destination. MAX sanity checks must reuse the existing authorized profile and must not create a new authorization or rotate tokens.
