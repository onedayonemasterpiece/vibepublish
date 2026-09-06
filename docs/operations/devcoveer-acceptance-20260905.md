# DevCoveer acceptance — 2026-09-05

Status: **Not confirmed by user / partial live acceptance**. Not full CI or release acceptance.

**Current connection status (2026-09-06):**
[OAuth, durable domain and automatic TLS renewal are deployed and verified](chatgpt-readiness-20260906.md).
Connect ChatGPT using OAuth, not a manual bearer-key field. Below is historical
Telegram/VK acceptance evidence; its dated failures are not current gate claims.

Latest: **VK postponed lifecycle and a real mid-publication crash/recovery now
verified**, including copied-photo IDs, explicit media preservation and exact
minute-level scheduling. See [VK completion](#vk-completion-and-live-crash-recovery)
for receipts and current remaining gaps; earlier failures below are retained as
historical evidence, not current blockers.

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
Streamable HTTP. **ChatGPT: OAuth** via the public consent page; see the current
connection guide above. Operator API clients may still use
`Authorization: Bearer <service_token>`.
Token and current endpoint were delivered/read back in owner's Saved Messages,
message **35826**. Never copy token into Git/chat logs.
Authenticated bootstrap 200, unauthenticated 401, real SDK initialization and
all eight tools verified again after final route repair. Protocol 2025-11-25.

User systemd units `vibepublish-acceptance-20260905-server.service` and
`vibepublish-acceptance-20260905-worker.service` are enabled/active, with linger,
private state `/home/dev/.local/state/vibepublish-acceptance-20260905` (0700),
SQLite WAL schema 4 and restricted filesystem writes. Server binds loopback18765.
Worker reads dedicated `VIBE_PUBLISH_TG_SESSION` from approved my-data-hub `.env`,
never falls back to EventsBot Telegram credentials. Ordinary Codex-task executor
is wired; see the current continuation below for actual successes and failures.

**Historical ingress durability gap (resolved; see 2026-09-06 guide):** a concurrent shared nginx regeneration removed the
new route during this run. Restored only exact VibePublish SNI/server block on top
of the new current config, preserving all other routes, with candidate/live
`nginx -t` and HUP, then actual public MCP readback. No network container restarted
by this task. Durable renderer patch `15fa5292362733ad2438261a491ebe561c60c573`
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

That checkpoint left automatic generation disabled behind inferred image-only
and hard billed-call gates. The owner subsequently rejected those gates for
ordinary Codex tasks. The continuation below supersedes that activation decision;
it does not falsely attest the legacy adapter or turn old tests into live proof.


## Current owner correction: ordinary tasks, MCP files and Kaliningrad

Explicit native execute publications automatically continue after visual work,
including NOW when no delivery time is supplied. Supplied date/time resolves in
Europe/Kaliningrad; the stand tenant timezone was changed and read back. Preview,
standalone and explicit human selection remain separate. VK acceptance remains
postponed-only regardless of the general NOW default.

The new `CodexTaskImagegen` uses native app-server tasks, pinned orchestration
model **gpt-5.6-luna**, owner Codex login/quota, and no API fallback. Native image
model ID is not reported and stays null. This is an ordinary task, not an
absolute image-only sandbox or a hard upstream billed-call guarantee.

Actual direct task **01a07234-66ed-77d3-b42d-9645fd167d18**, turn
**01a07234-7e26-79c1-ae63-4ea2e927786d**, produced a visually inspected Baltic
sea card “К морю” in 75 seconds. Native saved PNG exactly matched the native
imageGeneration base64 result, SHA256
`b03be1b7b0242035f7c19d5e0594e1501182ed35801d4be7dffc3a15a3626610`.

Live MCP file import **op_317a97d3ab004cf689a82c0fa25c7493** verified asset
**asset_f952576deea047148ea71ef7bd191c95**. Same-key replay returned the same
operation/asset. Actual tools/list exposes `openai/fileParams=["file"]` and the
server downloads/imports the file; no manual user HTTP upload is required.
The test used a real VK readback image URL and native photo identity, not an
invented ChatGPT attachment. Actual attachment handoff from this chat's UI has
not been demonstrated; server-side MCP import has.

### Failed first tasks and diagnosed causes (never resent)

- Generate **op_8d064e9986064cebb28e10013977bbab** /
  **visual_adf9d3049ad244a8871c7c0234d7457b** became core `outcome_unknown` /
  `imagegen_processing_unresolved` before any social attempt. Its native thread
  **01a07247-6ab5-71c2-aa26-3f516667d33f**, turn
  **01a07247-74ba-7543-86a5-5af8bfdff04f**, completed generation. Read-only recovery
  verified the same image, separately imported as original asset
  **asset_fabde2017a7b4cd3be1b01bffb14812e**; this did not repair or retry the old op.
- Distinct tune **op_5c06a3b0620e4ce3b2e085a49e48bb04** /
  **visual_d4c7f76a521b42a0b461dca587c661bf** likewise stopped before any social
  attempt. Native thread **01a0725c-b4cd-7422-8019-075b488fbaef**, turn
  **01a0725c-befe-70f1-a0f3-f42256f32262**, completed with zero native image items:
  its skill-reading shell command failed with bubblewrap namespace denial.
  No generated result is claimed and the tune was not repeated.

The early generic failure was reproduced without generation under the exact
systemd filesystem restrictions: `_read` opened `/` with O_RDONLY, but the
protected mount namespace permits traversal and not directory listing. Root and
ancestor descriptors now use O_PATH|O_DIRECTORY|O_NOFOLLOW; final file reads and
all path/ownership/hash checks remain intact. The same protected read probe now
returns succeeded for the original completed generation. No protection was lifted.

Separate confirmed adapter defects were fixed with regressions: numeric-only
VisualService usage metadata, and closing/resetting an incompletely initialized
owned app-server. Private diagnostics store exception class and frame locations,
not exception messages, locals, credentials or reasoning. These separate defects
are not falsely presented as the cause of the four-second live failure.

Sandbox investigation consulted official Codex sandbox/app-server documentation
and installed CLI0.153.0. Host AppArmor restricts user namespaces. A non-generating
legacy Landlock compatibility probe also rejected the managed permission policy.
No global sysctl, AppArmor profile or sandbox-disable setting was changed.

### Verified two-source composition → native queue

After the protected-path fix, the executor preloads the installed trusted
Imagegen skill in native developerInstructions. Sources are already visible as
localImage inputs; no shell skill read or shell output-copy is needed. Runtime
imports the native result itself. Sandbox protections remain unchanged.

**op_4f41b64cf9b845609abdda08bb11902d** /
**visual_579ffe5a6d3e43a3b5e254467bc2ee07** completed the actual public MCP →
worker → Codex task → built-in image_gen → automatic candidate selection →
Telegram native queue chain, with two existing owned source assets and one
prompt. Native thread **01a0726e-6b56-72d1-877f-a363f97a5a83**, turn
**01a0726e-7310-7170-89c4-3b09e4cec02d**, contains exactly one native image result.
Selected asset: **asset_9506059e3d054351b463b919442aa12f**.
Publication resource: **pub_55b0cc77e5704831b04ede0b4834406b**, revision2.

In `lovekenig` **-1002079710441**, scheduled message **8473** has photo
**5251650379513013697**, queued for **2026-09-07 18:37:11 Europe/Kaliningrad**.
Native queue readback found exactly one matching test caption. Downloaded image
was visually inspected: blue cup from the source, sea background, warm sunset,
exact readable “Чашка моря”, no clipped lettering. This is native provider binding
plus visual correspondence, not source/provider JPEG byte identity. Readback SHA
`ac5ac506b64effa64dcbb6ac3a3bbd41e6670c28bd824467455c40740710ef1f`.

Both own services were restarted after completion. Readback retained the same
scheduled ID, photo, date and downloaded bytes, still exactly one matching post.
Same-key MCP publish replay returned the same operation, visual job and asset.
No second generation or post was created. **8473 is deliberately left in the
native queue for owner review; it will publish at that time unless cancelled.**
Previous lifecycle cancellation8472 remains verified; no other queue objects
were modified by this new composition test.

### Additional NOW tuning test: native image, unresolved application operation

A distinct request edited the newly composed cup/sea image to a cool morning
palette and omitted delivery, targeting only the approved test group:
**op_c98747d028c440759032fba3ee8bd75e** /
**visual_f7ac2b87d64842adbe1c12d6f5fa937c**. It stopped with
`imagegen_submit_outcome_unknown`, no social attempts. Private diagnostics show a
thread/read transport RuntimeError, not the fixed root-directory failure.
Later read-only native lookup of **01a07271-bba8-7f23-a687-926c4f9161df**, turn
**01a07271-c158-71d2-b5ef-1b190c1e310d**, succeeded and showed one completed native
image. The original operation was not reset or resent. This test is not evidence
of an immediate generated publication. The discarded RPC payload does not prove
the exact transient server error; do not invent one.

Read-only executor recovery subsequently imported the same NOW-tune native PNG,
SHA256 `2b717819a6f1bf652fd69e7fc46c7ceee7e6514ca9ab6b0e56ec118e17ac393a`.
Visual inspection confirmed the cup, layout and “Чашка моря” lettering were
preserved while the sunset palette changed to cool morning. This proves actual
single-source image editing, not successful publication of that operation.


Transient native thread observation now retries only that saved thread/read,
at most three attempts of three seconds with 0.25/0.5-second backoff. This fits
inside the core's 15-second inspection bound. No thread/start or turn/start is
retried; response identity and artifact validation remain outside the retry.
Exhaustion remains unknown. Offline actual-service regressions cover recovery
and exhaustion with exactly one generation submit; this change does not reopen
any previously terminal operation.


### Verified generate → NOW with omitted delivery

A distinct new-art request with **no delivery field** completed the live public
MCP → worker → Luna task → built-in image_gen → automatic selection → immediate
Telegram test-group publication chain:

- Operation **op_856b0ca489af4815b2f1baf3deca97db**: verified/published.
- Visual **visual_1cc94ba7eb6a43d1939b2cd0d860398f**; selected asset
  **asset_f5a7ffe9410249a9a373246007d2157c**.
- Native task **01a0727e-737f-73c0-933d-bae4daf433a3**, turn
  **01a0727e-7ac9-7420-aad0-0ac3aad4e5f7**, one native image item.
- Approved basic group **-5283030741**, message **35834**, photo
  **5251393239821001509**, published **2026-09-05T16:55:30Z**.
- Native readback found exactly one matching caption in the recent40 messages;
  downloaded JPEG visually confirms emerald sea/sand and exact “Сегодня к морю”.
  SHA256 `bd8d5f313b7055ce69179f5879ef08780e7aaddf9ab603e620acac81f55b6ec5`.

After the final service restart, native readback retained the same message,
photo and downloaded bytes, still exactly one matching caption.

This is not a repeat of an uncertain command: different new-art intent, no source
image, new operation; prior unknown generation/tune operations were not reset.

## Previous engineering snapshot (superseded by VK completion below)

- **504 local tests and205 subtests passed**, two existing dependency-deprecation
  warnings,92.82s; compileall and diff checks passed. No existing tests disabled.
  This is **not** a successful hosted/full-CI claim or complete product acceptance.
- Actual public endpoint/auth/bootstrap and all eight MCP tools verified. Both
  own user-systemd services enabled/active. Runtime uses ordinary Luna image
  tasks; the obsolete inferred hard image-only/billed-call gate is not active.
- Telegram original media, custom emoji, ordering and native lifecycle are
  verified above. Generated NOW and composed scheduled publication are verified.
  Single-source tuning produced a verified native edited image, but its specific
  application publication stopped on a transient read failure and remains unknown.

Remaining obstacles, not missing destination names/IDs:

1. VK copied-photo owner/ID mapping is not automatically proven. Its original
   postponed post8 was removed and absence checked; the operation stays unknown.
   Do not resend or weaken media ordering/identity checks. VK full media lifecycle
   acceptance remains blocked.
2. Three historical visual operations remain terminal unknown. Read-only native
   recovery does not reopen core operations; no automatic reconciliation interface
   was added and no original ledger history was rewritten.
3. The actual current chat UI's attachment-to-MCP handoff and both original named
   business fixtures have not been end-to-end accepted. Server file-object import,
   original no-AI ingress and generated/tuned/composed native images are tested.
4. Restart after completed publications is tested. A real forced crash during an
   uncertain live publication and recovery of unfinished work is **not** tested;
   offline recovery tests do not substitute for that live gate.
5. Shared nginx renderer persistence patch (integration15fa529) is not activated
   in the shared controller; its update/restart permission remains unanswered.
   Another regeneration can remove the working route. Automated TLS renewal is
   also not independently verified.
6. Owner artistic/product acceptance remains pending. Scheduled test8473 remains
   live in the native queue for review and will publish at its stated time unless
   cancelled. No unrelated scheduled posts were changed.

Private/ignored evidence is under `artifacts/acceptance/codex-task-canary/`:
public-final.json, mcp-file-import.json, final-tests.log, compose-worker-live.json,
compose-replay.json, composed-native-readback*.json, downloaded readback images,
generate-now-worker-live.json and generated-now-native-readback*.json. Model
reasoning, social credentials and signed download URLs are not committed.


## VK completion and live crash recovery

Engineering verification completed 2026-09-05 22:48 UTC; owner confirmation pending.
Runtime code is acceptance commit `3860be5` plus subsequent evidence-only docs.
Both own services are active; schema4 migrated with a private pre-v4 SQLite backup
and integrity_check=ok. No business rows manually reset. Core branch HEAD remains
`24c33d9e74efa6a28fa48ecb70287c60bca7ef5c`; MAX/main untouched.

### Corrected native behavior

- Saved user-photo IDs really become community-copy IDs. Before/after exact
  provider JPEG bytes now prove their ordered binding; source asset hashes remain
  separate. Sanitized mapping survives final worker checkpoint persistence.
- `wall.edit` omitted attachments actually cleared photos in live post9. Explicit
  ordered verified IDs now go into both edit and reschedule, without reupload.
- `wall.edit` rounded an observed seconds timestamp to a whole minute. VK
  scheduled preflight now requires HH:MM / zero seconds rather than silently
  accepting a changed time. Requested/effective time must still match exactly.
- Native post ID stayed **10** throughout the successful queued lifecycle. That
  observation is distinct from the changing photo IDs; no untested assertion is
  made about the later queue-to-public-wall transition, which was not authorized
  for this VK stand.

Official contract consulted: [VK wall method schema](https://github.com/VKCOM/vk-api-schema/blob/master/wall/methods.json)
and [photo schema](https://github.com/VKCOM/vk-api-schema/blob/master/photos/objects.json).
Omitted-attachment preservation/second precision were incorrect assumptions, not
promises in those schemas. Required Opus consultation was attempted with the
project CLI; it returned “Not logged in”. Independent read-only reviewer found
original-actor-epoch and final-proof persistence gaps, both fixed and tested.

### Unknown history preserved, not resent

Old post8: owner-only resolution **op_176086aa329f476b9aee050a58d77207**, publication
`pub_957f3d1f136746a5b10fc0edffcedaa8` revision3, proves complete native queue absence
and exact published lookup absence. Original unknown publish/attempt unchanged.

Post9: publish **op_73a5df2be46948d1a11d258b5ab091d4** verified ordered copy mapping:
`photo868977531_457260398/399` → `photo-241261191_457239026/027`.
Edit **op_8aefc9df8b5646a5a868eed2a8c3a94d** became unknown when the live omission
bug cleared media. No repeat; exact own test9 was separately deleted with native
read-before/read-after safeguards (not claimed as MCP lifecycle acceptance).
Resolution **op_7d029dc154cf43ad956311131f3a8b5f** verified absence at publication
revision4 and released only that attempt's quarantine; original edit stays unknown.
An intervening v2 approval **op_26b47863ed0b4c9b9472a1a60060d6dc** was blocked by
quarantine before dispatch (`dispatched=0`), with no native post created. It was
not reopened. New v3 canary began only after recorded absence resolution.

### Successful full VK lifecycle

Publication **pub_d8b9c3872c774637a13cb8648b6a93be**, target **-241261191**, native
post **10**, revisions1→5, using two existing original image assets (no new AI):

| Step | Operation | Observed result |
|---|---|---|
| preview | op_799b127cf69d4146a8dba16c081cab0c | needs_approval, no publish |
| approve/publish | op_ce311c23988647beaade6e574355f246 | native scheduled10 |
| edit | op_50df0404d17d4893a6d632f37c44c061 | same10, exact new text, media retained |
| reschedule | op_e23b4ea7e00842c6b59e69890450b956 | same10, exact new native time |
| cancel | op_5aae953909584dd2be74ce0ef7cb95e8 | cancelled, complete queue empty |

Initial native time **2026-09-08 00:44 Kaliningrad** (2026-09-07T22:44:00Z),
rescheduled **2026-09-09 00:44 Kaliningrad** (2026-09-08T22:44:00Z), always >24h.
Ordered community photos **457239028, 457239029** survived edit/reschedule.
Independent authenticated native readback downloaded both: blue TEST01 then orange
TEST02, visually inspected; one exact matching post, no duplicates. Exact JPEG
SHA256 in that order:

- `39dff7fd7f66a0f4f294a89b6fd3e55b895126b4b41fbf1271911eaf27f68f9f`
- `b6ddae52a555baaacc63fe8bdc8f89f997ade5ed132948c886ce60926b7e583f`

### Real interrupted publication recovery, not just completed restart

New explicit VK canary preview **op_72bbecb49e8d4fba9981a643f50255a6**; publication
**pub_04e6da51edfc4d998b669a23945b4618**. Approval
**op_894f709d03b44445942d347cbcb63e08**, attempt
**attempt_cfad6735581f4030bb0286c69df348a2** created native post **11**.
A temporary deployment-only wrapper, armed for this exact operation/target and
`vk_response`, first delegated the real durable checkpoint, fsynced a one-shot
marker, then SIGKILLed **only its own worker PID692967** at 22:46:24 UTC.
Systemd automatically restarted once as PID693127; natural lease expiry reclaimed
fence2 at22:46:53 and read-only reconciliation completed scheduled at22:46:56.

Ledger: one attempt, one dispatch event, two uploads before the crash and no
uploads/submissions after it; final sanitized mapping preserved. Independent
complete queue read found exactly one post11, photos **457239030, 457239031**, same
ordered byte fingerprints. No manual clock/lease/ledger edits and no wall.post
resend. Temporary own-service drop-in removed and normal worker restored.
MCP cancel **op_5ab3e2e45d124f4ebaf3a11430939136** verified native11 absent; independent
complete VK postponed queue is now **empty**. All new VK canary posts cleaned up.

### Checks and current remaining gaps

- **539 tests +205 subtests passed**, two dependency deprecations; compileall and
  git diff --check passed. This is local integrated testing, **not hosted/full CI**.
- Public MCP authenticated200/unauthenticated401 and eight tools checked again.
- Prior Telegram native lifecycle, custom emoji, media order, original ingress,
  Luna image generation and automatic generated/composed publication evidence
  remain valid. Image task model remains **gpt-5.6-luna**, native Codex image_gen,
  owner login/quota, no API fallback.
- Current UI attachment-to-MCP handoff and the two original business reference
  images still lack end-to-end client acceptance. Server-side real file-object
  import is verified; do not describe that as observed current-client behavior.
- Three historical visual operations remain terminal unknown; their native task
  evidence exists, but this social-attempt absence resolver does not reopen them.
- Domain/TLS gap from this snapshot is **superseded** by the
  [2026-09-06 deployment verification](chatgpt-readiness-20260906.md): current
  runtime renderer preserves the route and unattended renewal/hook dry-run passes.
- Owner artistic/product acceptance pending. Telegram scheduled review8473 still
  exists for **2026-09-07 18:37:11 Kaliningrad** and will publish unless cancelled.
  No unrelated scheduled posts were changed.

The crash marker `crash-canary-fired.json`, one-shot wrapper, and filtered
`crash-systemd-journal.json` preserve the response-checkpoint seam and actual
`code=killed, status=9/KILL` / restart-counter1 evidence.
`crash-final-checkpoint.json` is explicitly the post-recovery snapshot, not a
claimed pre-crash database capture.

Private ignored evidence: `artifacts/acceptance/vk-completion/` contains exact MCP
receipts, native readbacks/downloads, lifecycle/copy checkpoints, crash ledger and
final tests. Credentials, signed URLs and provider private bodies are not committed.
