# Local technical media-store clients

**Requirement: Fixed (owner, 2026-10-18). Implementation: Not confirmed by user until live E2E.**

Canonical host policy: https://github.com/onedayonemasterpiece/codex-devcoveer-mcp/blob/main/docs/operations/local-service-connections.md

A long-running local service must use the existing VibePublish loopback HTTP API with
a **dedicated non-owner service principal**. Public MCP OAuth/PKCE/browser consent
are for external user clients, not for this connection. Use the existing normal
token hash authentication; no new gateway, session manager or authentication daemon.

## Principal and exact topic grants

One-time LOCAL owner administration of the existing VibePublish ledger:

- Provision a non-owner principal with **only** `bootstrap`, `status`,
  `media.store`. The local CLI accepts repeated `--scope` values. Its token
  is output exactly once and must go directly into the consumer's owner-protected
  secret file, **never** to chat, CI, the command history, reports or logs.
- Bind its alias to the existing **KB-only Telegram peer**, with **only**
  binding right `publish`. A chat binding does **not** authorize every topic.
- Use the admin command `service-media-topic --principal <service-id> --alias
  <existing-kb-alias> --topic 2` and similarly `--topic 4`. The exact topic
  IDs are stored in the existing VibePublish SQLite as scoped authority. Omit
  all other destinations, publication management and social authoring scopes.
- The same command with `--revoke` disables one topic; it fences all earlier
  principal epochs and operations. Old generic owner/partner tokens gain no
  extra rights through this feature.

The private media tool itself verifies **each** put/list/get/search against the
principal's exact binding and topic grant. Search is confined to the principal's
own archive entries, not the owner's other media. Download-cache assets are
linked to their owning archived publication before the service can fetch bytes.
A principal with `media.store` cannot call ordinary publish, visual-generation,
destinations, social read or engagement tools.

## Recovery/verification

Keep exact stable request keys and operation IDs. Never make a new send on a
lost/unknown outcome. Source bytes remain in RKB until provider-backed readback
and original SHA-256; only then may RKB mark the archive verified. For RKB,
topic 2 holds source PDF/DjVu, topic 4 illustrations. Local HTTP, existing
`Host` admission and credential checks all still apply. No bearer-less
loopback endpoint is introduced.

Code/test/CI or token provisioning alone does not prove live readiness. Required
live acceptance: a permitted archive send; denied third topic; same-key replay;
provider topic/destination/receipt; exact original bytes fetched again; restored
pending RKB archive status. No other product sessions or bindings are altered.
