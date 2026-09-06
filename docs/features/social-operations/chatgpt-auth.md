# ChatGPT MCP authorization

Status: **Not confirmed by user**; implementation and owner UI acceptance are separate gates.

## Requirement delta (2026-09-06)

The scoped-principal/current-epoch rules in `implementation-design-v1.md` remain
unchanged. The development bearer transport in `social_operations/server.py`
is insufficient for ChatGPT onboarding. Add an opt-in OAuth authorization server
using installed MCP SDK protocol handlers; do not change default local transport.

- Static exact HTTPS issuer and resource `/mcp/`, discovery and bearer challenge.
- Public-client DCR accepts only the exact documented ChatGPT callback
  `https://chatgpt.com/connector_platform_oauth_redirect`; PKCE S256 mandatory.
  No wildcard redirects, arbitrary client URLs fetched, registration of users,
  social credential passthrough, or new publication authority.
- Browser owner consent requires the existing service token in a same-origin POST
  only, secure browser-bound CSRF proof, explicit consent and a short-lived request.
  Never place the service token in URLs, cookies, HTML, OAuth tokens or logs.
- Separate private persistent SQLite auth state stores hashed random credentials.
  Codes are single-use, client/redirect/resource/PKCE bound and expire in 2 minutes.
  Access expires in 10 minutes; refresh rotates, expires in 30 days, and reuse
  revokes the whole family. Current principal/tenant activity and epoch are checked
  on consent, exchange, refresh and every authenticated request.
- Existing scoped actor snapshot bounds every grant. Any scope or owner flag change
  requires fresh consent (fail closed, including broadening). Existing epoch checks
  fence authority changes across requests; no scope/owner escalation.
  Explicit revocation invalidates the family; original service bearer stays usable.
- Host/origin, duplicate parameters, request size/time, endpoint rates and retained
  state are bounded: 16 KiB POST, 8 KiB query, 10 second reads, 120 auth
  requests/minute global and 20/minute per socket peer/path; 1,000 clients,
  families and pending requests, 20,000 retained credential hashes. Public metadata
  contains no principal or destination data. Access logs must remain disabled.

Source: [official OpenAI authentication documentation](https://developers.openai.com/plugins/build/auth).
MCP SDK handlers provide protocol validation; resource checks, exact callback policy,
private persistence and consent/current-authority enforcement belong to this project.

## Verification

34 focused OAuth tests and four existing transport regression tests passed
(38 total; two dependency deprecation warnings). Includes actual MCP initialize,
tools/list and bootstrap using OAuth, restart persistence, one-use code, binding
rejections, CSRF, grant-authority changes denying real HTTP/MCP requests, refresh
rotation/replay revocation, expiry, exact metadata issuer and non-secret persistence.
No social effects are performed by these tests. Not hosted/full CI.

Deployment readback, desktop/mobile consent rendering and actual ChatGPT account
linking remain integration/user-surface checks; see the main acceptance report.

### Operator integration

Use `social_operations.oauth.create_oauth_app(store, auth_db=private_path,
issuer="https://mcp-vibepublish.kenigevents.ru")`. Issuer must be an exact HTTPS
origin without a trailing slash; resource defaults to issuer + `/mcp/`. The auth DB
must be separate from the business ledger, with a private 0700 parent and 0600 file.
Default `create_app` bearer transport is unchanged. OAuth tool descriptors advertise
the `vibepublish` authorization scope but never broaden underlying authority.

The installed MCP SDK revocation request model requires `client_secret` despite
public-client `none` authentication. The wrapper normalizes its absence to an empty
field before SDK validation, rejects non-empty secrets/Basic auth, and retains SDK
client matching/revocation handling. SDK URL models normalize bare origin slashes;
metadata is serialized with the exact configured issuer to satisfy RFC 9207.

Public DCR requires explicit `token_endpoint_auth_method: none`, the sole supported
callback, grants `authorization_code` and `refresh_token`, and scope `vibepublish`.
The consent page accepts the owner service token only in its protected POST form.
No client secret must be configured in ChatGPT; choose OAuth/DCR onboarding.
Opus architecture consultation attempted with `claude --model opus --effort high`;
CLI returned `Not logged in`; no secrets were submitted.

### Bounded registration availability

Anonymous DCR registrations are capped and do not automatically expire. Reaching
1,000 rejects new registrations but does not revoke existing clients or grants.
Operator recovery must audit inactive registrations in the separate OAuth database
and preserve every client referenced by a live pending request or grant; no automatic
client deletion or business-ledger modification is performed. This is a bounded
availability limit, not an unlimited public identity service.

### Browser consent regression — 2026-09-06

Status: **Not done** pending corrected real-browser acceptance. Offline protocol
checks did not expose a navigation-specific browser failure: `no-referrer` on the
consent document caused its HTML POST to send `Origin: null`, correctly denied by
the origin boundary. The consent document alone must use `strict-origin` (origin
only, never its request query). Null origins remain denied; all other responses
keep `no-referrer`. Chromium may also enforce `form-action` on a POST's 303 redirect,
so its CSP must allow only `'self'` plus the exact registered ChatGPT callback. The
form action itself stays `/oauth/login`; no service token is posted cross-origin.

References: [MDN Origin effects](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header),
[MDN form-action redirects](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/form-action).
