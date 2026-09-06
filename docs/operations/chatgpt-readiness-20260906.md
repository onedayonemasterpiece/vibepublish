# ChatGPT connection readiness — 2026-09-06

Status: **Not confirmed by user**. Server-side connection gates are deployed and
verified; owner intent to finish is **Fixed**. Actual owner ChatGPT linking and
attachment handoff have not yet been observed.
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
- Initial domain-persistence suspicion was disproved by runtime inspection: the
  other authorized shared-edge stream had already deployed a combined renderer.
  The unnecessary controller-restart question was withdrawn; verification below.

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


## Public OAuth and MCP acceptance

Deployed application commit **d2b8e3b** (OAuth5c55fd0, stand wiring413843e,
browser correctiond2b8e3b). Only the isolated VibePublish server was restarted.
Worker remains enabled/active. Dedicated OAuth DB is separate from the business
ledger, directory0700/file0600. Existing operator bearer still returns bootstrap200;
anonymous requests return401 with resource discovery. Public metadata returns200.

Real headless Chromium visited the public HTTPS hostname, rendered the Russian
owner consent form at1280x800 and390x844, and submitted it with the service token
in a same-origin POST. A browser-only defect missed by HTTP fixtures was corrected:
strict-origin on the consent GET preserves the POST Origin; null origins remain
forbidden, and the exact fixed callback is allowed by CSP. No token in URLs/logs.

The final canary intercepted the outgoing ChatGPT callback at the CDP Fetch
request stage and asserted GET/no POST body. This verifies the real browser's
redirect and server grant chain, **not** installation inside an actual ChatGPT
account. A preceding diagnostic used Playwright page.route, which does not
intercept redirect hops; its interception failure was a harness defect, not a
second server failure. No owner ChatGPT session was present in that browser.

| Check | Observed result |
|---|---|
| Discovery / DCR | exact issuer/resource, S256; registration201 |
| Browser consent | same-origin POST303, callback code/state/iss verified |
| Code exchange / reuse | PKCE exchange200, repeated code400 |
| MCP over OAuth | initialize, all8tools, get_started |
| Original image import | verified, replay returns same operation and asset |
| Refresh |200, token rotation |
| Own server restart | systemd stop/start at05:13:50UTC, PID226548; grant still works |
| Canary revocation |200; subsequent access401; original operator token still works |

File import **op_77d5660393214563b78c09fe1f2184f7**, asset
**asset_d9b576867d08428795d6e6903ae73f33** used a real prior VK image readback URL
through the MCP file-object contract, with no AI or social publication.
`openai/fileParams:["file"]` is advertised on the visual tool. This is not proof
that ChatGPT has handed off the two original conversation attachments.
All37 business operations have complete=1/work_state=done; historical terminal
unknown results remain untouched and are not retried.

Evidence: `oauth-issue.json`, `oauth-browser-events.json`, desktop/mobile PNGs,
`oauth-verify.json`, `oauth-refresh.json`, `oauth-after-restart.json`,
`oauth-service-restarts.json`, `oauth-revoke.json`, `final-runtime.json`.
Private canary credentials are not committed; its grant family is revoked.

## Checks and delivery boundary

Final integrated local suite: **576 tests +205 subtests passed**, two dependency
deprecation warnings. Focused auth/transport/launcher suite: **41 passed**.
Compileall over implementation/deployment/tests/verification and git diff --check
passed. Existing tests are enabled; hosted CI, clean-environment wheelhouse and
Python3.13 matrix were not run in this continuation and are not claimed.
Core remote HEAD remains24c33d9e74efa6a28fa48ecb70287c60bca7ef5c.
Changes are confined to the acceptance branch; MAX/PR2, main, original checkout
and unrelated production services were not changed.

## Connect in ChatGPT

1. Enable Developer mode if available for your account/workspace. Current official
   navigation: Settings → Security and login → Developer mode.
2. Add a custom MCP connection named **VibePublish** at
   **https://mcp-vibepublish.kenigevents.ru/mcp/**, using **OAuth**. Public-client
   dynamic registration is supported; do not enter a client secret or treat the
   operator bearer as a ChatGPT API-key setting.
3. In the opened **mcp-vibepublish.kenigevents.ru** consent page, enter the existing
   VibePublish token from Saved Messages35826 and confirm connection. Never enter
   Telegram/VK passwords or sessions. The existing operator token was not rotated.
4. Confirm8tools appear; in a new chat call get_started without publishing. Then
   attach an image and ask to import it without AI or publication. Keep the actual
   returned operation/asset ID to close the remaining ChatGPT handoff check.

[Official ChatGPT connection instructions](https://developers.openai.com/plugins/deploy/connect-chatgpt).
This environment has neither an authenticated owner ChatGPT browser nor this new
connector in its available tools, so account installation cannot be performed or
attested here. No missing server-side OAuth/domain/TLS gate is currently observed.

## Remaining boundaries, not hidden readiness claims

- Owner ChatGPT connection, actual attachment handoff and artistic/product
  acceptance remain **Not confirmed by user**. Both original reference images
  still need that end-to-end client acceptance, not another synthetic source.
- Three historical terminal-unknown image tasks stay in history; never regenerate
  them automatically or rewrite their outcomes. Prior successful live Luna tasks
  and social readbacks are documented in the preceding acceptance report.
- This remains an isolated test service, not unrestricted production publishing.
  VK lovekenig remains postponed-only at least24hours ahead; immediate Telegram
  writes remain limited to the approved test group. General no-time means NOW
  behavior does not override these live-target restrictions.
- Existing generated Telegram review8473 is scheduled for **2026-09-07
  18:37:11 Kaliningrad** and will publish unless cancelled. It was not altered in
  this continuation. VK test posts were previously cancelled; no new ones created.
- Raw non-chat HTTP uploads retain the shared edge body limit described above.
  OAuth anonymous client registration has bounded capacity, documented in
  [the authorization contract](../features/social-operations/chatgpt-auth.md).
