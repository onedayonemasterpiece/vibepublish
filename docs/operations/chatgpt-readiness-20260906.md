# ChatGPT connection readiness — 2026-09-06

Status: **Not done** until deployed checks; owner intent to finish is **Fixed**.
This is the continuation of the [stand acceptance](devcoveer-acceptance-20260905.md),
not authorization to expand live destinations or alter MAX/main/production.

## Requirement delta before implementation

- Already present: private authenticated eight-tool MCP, real Telegram/VK native
  lifecycle, original file import, Luna image tasks and interrupted-worker recovery.
- Missing: ChatGPT-compatible OAuth onboarding. Existing manually provisioned
  Bearer token is an operator API credential, not a supported ChatGPT custom-key
  setting. Add opt-in OAuth2.1 discovery, PKCE, explicit owner consent and revocable
  resource-bound grants. Existing local bearer access stays compatible; no public
  unauthenticated publishing and no social credentials in browser/ChatGPT.
- Needs clarification/verification: actual ChatGPT account connection and attachment
  handoff require its client to participate. Browser/protocol fixture tests cannot
  prove an owner-account connection that has not occurred.
- Renewal: DNS-hook staging dry-run succeeded, but invoked user-browser YC auth.
  Remove that automation dependency for this certificate only by switching its
  renewal authenticator to the already served HTTP-01 webroot, using certbot
  reconfigure/staging validation. Do not change other certificate lineages, web
  routes, DNS zones or shared timer. Verify configured deploy-hook nginx-t/HUP.
- Domain persistence: shared controller still carries old renderer. Root requested
  explicit scope to update/restart only vpn-bot, with no nginx/xray/hysteria restart
  or other route changes. Pending answer; no hidden injection or watcher workaround.

## Sources

[OpenAI authentication contract](https://developers.openai.com/plugins/build/auth)
requires OAuth authorization code/PKCE with resource and issuer validation; it does
not support arbitrary custom API keys in ChatGPT.
[Certbot renewal configuration](https://eff-certbot.readthedocs.io/en/stable/using.html#modifying-the-renewal-configuration-of-existing-certificates)
describes reconfigure as a staging-validated change to the renewal options.

## Evidence

Private logs/checks: `artifacts/acceptance/chatgpt-readiness/`.
No tokens, sessions, callback codes or signed file URLs are committed.


## Completed independent checks

### Domain regeneration

Earlier acceptance text was stale. Another authorized shared-edge reconciliation
had already deployed `vpn-server-vpn-bot:shared-edge-e5fcabe` with VibePublish enabled,
alongside WL and Dataset Loop. Current host checkout HEAD `06c35f8` records this.
Runtime renderer (fixture DB only, no live render_all/apply) reproduces the working
nginx config **byte-for-byte**, SHA256
`bd9b57e0e00720ae98698365e797913a0bfa22adff25d6dc0f10fdea7a79755b`,
including exactly one VibePublish SNI entry and server. No shared controller or
network container was restarted in this continuation; requested restart permission
was withdrawn as unnecessary. No other origin changed.

This controller does not include the optional 20MiB raw HTTP-body patch. ChatGPT
file-object imports download the image server-side and do not need that patch;
non-chat raw `/v1/assets` uploads remain subject to the edge's default body limit.
Do not carry forward the old blanket large-raw-upload acceptance claim.

### Automatic certificate renewal

Only `renewal/vibepublish-acceptance.conf` changed: certbot's supported reconfigure
switched from manual DNS hooks (YC user browser auth) to webroot HTTP-01 at the
existing challenge location. A unique harmless HTTP challenge probe returned200
with exact bytes and was removed. New challenge directory was created under the
existing webroot mount; no nginx routing change or DNS record modification needed.

Staging reconfigure passed, then independent `renew --cert-name
vibepublish-acceptance --dry-run --run-deploy-hooks` passed using the saved webroot
configuration. The real deployment hook passed nginx-t and sent graceful HUP.
Nginx container ID/start time unchanged; no container restart. All other renewal
files and all live certificate/key bytes unchanged. Existing daily03:17UTC timer
(+up to30min jitter) is enabled and already invokes renew plus that deploy hook.
Public certificate remains valid through2026-12-04. No future successful issuance
is promised; this is actual unattended staging/activation-path evidence.
