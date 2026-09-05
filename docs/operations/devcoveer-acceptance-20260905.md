# DevCoveer acceptance — 2026-09-05

Status: **Not confirmed by user / partial live acceptance**. Not full CI or release acceptance.

## Source and deployed scope

Origin core HEAD checked as `24c33d9e74efa6a28fa48ecb70287c60bca7ef5c`,
three documentation commits after checkpoint `f91f92cf6781c617719721a27f5b6c9015344c60`.
Acceptance branch: `work/vibepublish-devcoveer-acceptance-20260905`, checkout
`/home/dev/projects/vibepublish-acceptance-20260905`.
New independently developed image adapter (not archive restoration), narrow
creator-owned basic Telegram group immediate-publish permission, and absent/null
cancel receipt timestamp correction are integrated. MAX/PR #2, main and original
working checkout remain untouched; existing tests/CI were not disabled.

## Connection

MCP: **https://mcp-vibepublish.kenigevents.ru/mcp/** (also exact `/mcp`).
Streamable HTTP, `Authorization: Bearer <service_token>`.
Token and current endpoint were delivered/read back in owner's Saved Messages,
message **35826**. Never copy token into Git/chat logs.
Authenticated bootstrap 200, unauthenticated 401, real SDK initialization and
all eight tools verified again after final route repair. Protocol 2025-11-25.

User systemd units `vibepublish-acceptance-20260905-server.service` and
`vibepublish-acceptance-20260905-worker.service` are enabled/active, with linger,
private state `/home/dev/.local/state/vibepublish-acceptance-20260905` (0700),
SQLite WAL schema 3 and restricted filesystem writes. Server binds loopback18765.
Worker reads dedicated `VIBE_PUBLISH_TG_SESSION` from approved my-data-hub `.env`,
never falls back to EventsBot Telegram credentials. Automatic image executor disabled.

**Ingress durability gap:** a concurrent shared nginx regeneration removed the
new route during this run. Restored only exact VibePublish SNI/server block on top
of the new current config, preserving all other routes, with candidate/live
`nginx -t` and HUP, then actual public MCP readback. No network container restarted
by this task. Durable renderer patch `ec9012c47fd7925f2c0cfc9ee336f13139ebfba3`
is saved in separate vpn-server integration checkout, not installed into running
control bot. Owner permission to update/restart that shared controller is pending.
Another regeneration can still remove this route. Dedicated TLS expires 2026-12-04;
automated renewal has not been independently verified.

## Real Telegram acceptance

Authorized links resolved using dedicated session, not guessed IDs:
basic test group **-5283030741**, lovekenig **-1002079710441**.

| Step | Operation | Native/result |
|---|---|---|
| Group preview | op_c4021597f62c4753867f0734fa56dd03 | needs_approval |
| Group approve | op_e711658c16b5425ba42f564423ea492b | verified; messages **35832,35833** |
| Channel preview | op_0b7a1c1978d3479482f98f3fec24f0b1 | needs_approval |
| Native schedule | op_741b765f0c7442da918ced0f9060fab3 | scheduled **8472**, 2026-09-07T14:03:17Z |
| Edit | op_246d20576d5f465b9f59a18e3a1dc3dd | same object8472, scheduled |
| Reschedule | op_f041b6cd59c94824a59114146ca1e031 | 2026-09-08T14:07:00Z |
| Cancel | op_a7e32a699427499ebb722865cf28e4f6 | cancelled, revision5;8472 absent from native queue |

Cancellation initially succeeded natively but failed strict MCP status projection
because requested_at was null. Fixed omission for future receipts and legacy
read projection only, without history/DB rewrite; final **read-only status**
confirmed cancelled. Cancellation was never resubmitted.

Custom emoji catalog operation `op_55806e4aaa984c86ab7eb459eead5893` fetched
200 real entries from lovekenigofficial. Selection [1,2,1] resulted in native
entities **5388964340386780923 → 5433637661032078632 → 5388964340386780923**,
verified in published Telegram readback. Real picker rendered at desktop/mobile;
animated native-client rendering remains unverified.

Album native grouped_id **14308936062568610**; photo IDs
**5251393239821001175,5251393239821001176**. Downloaded photos visually verified:
blue TEST01 then orange TEST02. Telegram transcoding is not source-byte equality.
Recent30 history had exactly one matching caption/two album members. Replaying
same original approve idempotency key returned original operation, no new send.
Server/worker restarted after schedule completion; existing objects/token/readback
survived and scheduled object could be edited/rescheduled/cancelled. No live crash
inside an uncertain external-effect window was induced; offline crash tests are
not that live acceptance.

## Images, VK, tests and remaining work

Two actual built-in `image_gen.imagegen` calls were executed by **gpt-5.6-luna**
agent, imported through asset importer, published and read back. Image backend
model is not exposed. This is standalone generation, **not automatic worker
integration**. Newly developed adapter has local process/isolation/failure tests,
but verified image-only tool confinement, hard upstream image-call budget and
actual native CLI event-contract evidence are still missing. It stays disabled;
real integrated generate/tune/compose remains unaccepted.

Existing authorized VK user auth was checked read-only (user868977531).
Owner subsequently approved https://vk.ru/lovekenig, postponed only. Exact
resolution: group241261191, admin_level3. Dedicated wrapper rejects other groups,
immediate sends, forward/delete and schedules less than24h ahead; reads remain
possible after expiry. See new live evidence below.

Prior local full pytest: **375 passed, 199 subtests passed**, 77.62s; compileall
passed. No skips/exclusions; this is not full hosted CI. Initial missing-package,
Chromium and missing-module failures were real earlier results, now superseded
for this acceptance checkout by the final run. Edge renderer has16 passing tests.

Ignored evidence: `artifacts/acceptance/continuation/`, including final-pytest.xml,
public-mcp-final.json, channel-cancel.json, native-final-readback.json, all step
receipts, real image/downloads, picker screenshots, and pre/post ingress configs.
Some private receipts contain review tokens: do not publish artifacts wholesale.

Remaining: VK media-identity reconciliation/lifecycle; automatic image executor activation and full
visual workflow; durable shared renderer deployment; TLS renewal verification;
live uncertain-effect restart acceptance. User confirmation remains required.


## Prompt-first + original ingress continuation

Owner explicitly permits skipping intermediate image selection when an explicit
visual request accompanies execute-to-future-native-queue. Implemented prompt
alias for all three modes, optional generate references, unchanged originals via
media without visual, and safe automatic scheduled continuation. Preview,
standalone and immediate requests cannot gain publication authority. Legacy
brief/copy remains supported; prompt-only typography is unverified model output.

Added authenticated binary `POST /v1/assets`,20MiB image-only ingress, dedicated
idempotent operation namespace, current principal scopes/quota, and original plus
sanitized derivative. JSON/MCP limits remain512KiB. Two concurrent decode tasks
run off the event loop; the receive buffer is bounded per request, not globally
by this decode semaphore. Exact VibePublish nginx host alone now allows20MiB.
Pure-MCP chat attachment bridging and URL import are not implemented.

Live public upload1455945bytes returned200; replay returned the same
**asset_1f61f1e0a0234d728547ca1913cd3647**. Authenticated GET hash matched;
original source hash matched; no-auth401; zero generator calls. Actual public
MCP tool schema includes prompt for all modes and sources for generate.

### VK live evidence, not a successful media acceptance

Preview **op_3061d4b05f4345f1a31e4bb87a19faf8** reached needs_approval.
Approve **op_1044c3589743450c97a096155ae04db5** created native postponed
**-241261191_8**, but readback failed media_identity_or_order_mismatch:
uploaded **photo868977531_457260392,photo868977531_457260393** became
**photo-241261191_457239024,photo-241261191_457239025** in the provider queue.
Exact readback had one matching test caption. Downloaded photos were visually
verified blue TEST01 then orange TEST02. This is visual correspondence, not
verified provider-ID mapping. Original uploaded photo lookup returned API200
access error, so correspondence was not promoted to an automatic binding.

No publication resubmission or history rewrite. The independently identified
test8 was cancelled once via an explicitly guarded native cleanup (not the MCP
lifecycle) and absence in postponed queue confirmed. Original app operation stays
outcome_unknown; edit/reschedule lifecycle for this image post is not accepted.
Do not retry it or silently weaken media checks.

Final integrated local suite: **417 passed,199 subtests**, two dependency
TestClient deprecation warnings,74.66s. Compileall passed; edge21 tests passed.
This is not a hosted full-CI claim. Evidence:
`artifacts/acceptance/prompt-postponed/` (private/ignored), including
http-original-upload.json, live-contract.json, final-pytest.xml, native8 readback,
media downloads and vk-test8-cleanup.json.

Automatic built-in generation remains disabled: exact installed CLI0.153.0
research did not establish native image-only allowlisting or pre-dispatch hard
upstream call budgets. Required controls are in
[the executor activation contract](devcoveer-imagegen.md#activation-is-deliberately-not-claimed).
This is a concrete integration blocker, not a reason to claim prompt support or
scripted tests prove real generate/tune/compose acceptance. Original upload and
native original-media publishing do not require that executor.
