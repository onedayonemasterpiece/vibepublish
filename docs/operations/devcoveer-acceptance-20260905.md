# DevCoveer isolated acceptance — 2026-09-05

Status: **Not confirmed by user / partial; live acceptance blocked**.

## Source and boundaries

PR #1 branch HEAD was read from origin and GitHub as
`24c33d9e74efa6a28fa48ecb70287c60bca7ef5c` (unchanged at final origin recheck).
Only three documentation commits follow owner checkpoint
`f91f92cf6781c617719721a27f5b6c9015344c60`.
Isolated checkout: `/home/dev/projects/vibepublish-acceptance-20260905`.
No core, adapters, tests, CI, MAX/PR #2, main or production edits.
`adapters/codex_imagegen.py` remains absent; no archive or replacement was used.

## Running service and connection

Host: `DevCoveer`, non-root user `dev`. Dedicated user-systemd services:

- `vibepublish-acceptance-20260905-server.service`
- `vibepublish-acceptance-20260905-worker.service`

Both enabled and active; user linger is enabled. Server listens only on
`127.0.0.1:18765`; worker has no native, fake or image executor configured.
Separate venv and SQLite/WAL ledger, schema version 3. No production data reused.
State: `/home/dev/.local/state/vibepublish-acceptance-20260905` (0700).
Unit files: `/home/dev/.config/systemd/user/` (0600), with no-new-privileges,
private tmp, read-only home/system and write access limited to the state directory.

MCP Streamable HTTP endpoint: `http://127.0.0.1:18765/mcp/`.
Connect on DevCoveer, or forward remote port 18765 through the existing IDE/SSH
connection. Supply HTTP `Authorization: Bearer <service_token>`; the operator
can obtain the value locally from `owner-token.json` in the private state directory
(0600). Do not paste the token into chat or Git. No public HTTPS/OAuth endpoint
was created; remote cloud clients cannot directly reach this loopback endpoint.

Real SDK ClientSession initialize/list_tools/get_started succeeded: protocol
`2025-11-25`, eight tools, skill hash
`d5044f0a018dc5bfca566944230e52655f201378927cce75bdf28099490fdade`.
Authenticated HTTP bootstrap returned 200; unauthenticated returned 401.
Server and worker were restarted only within this authorized isolated stand;
new PIDs were observed and the same token/MCP readback survived restart.
This verifies service restart, not recovery of an in-flight live publication.

## Executed checks

- Fresh venv from committed requirements.lock; installed application without
  dependency resolution. Dependency-input verification and package check passed.
- Compileall for social_operations, adapters, tests and scripts/verify passed.
- Targeted runtime/providers/emoji/contracts/sdk/inspection/verification run:
  254 passed, 3 failed, 199 subtests passed. Failures were missing project package
  installation for a subprocess and absent Chromium build 1200 (two viewports).
- After installing the project and pinned Playwright Chromium, the affected
  emoji transport and SDK files were rerun: **11 passed**. No tests changed.
- Real Telethon 1.44.0 compiler/wire verification passed, including three native
  entities. No Telegram RPC was used.
- Browser fixture screenshots inspected at 1440x900 and 390x844: selected chain
  2 -> 3 -> 2, no horizontal overflow or page errors. These are synthetic fixture
  images, not real Telegram custom-emoji media/animation acceptance.
- Strict complete pytest invocation: **collection error** for missing
  adapters.codex_imagegen. Full suite/CI is NOT green.
- Additional visuals-only diagnostic with --continue-on-collection-errors:
  **38 passed, 1 collection error**, nonzero exit. The flag was diagnostic only;
  existing tests and mandatory CI remain unchanged.

Evidence is local and ignored by Git in `artifacts/acceptance/`: logs, JUnit XML,
SDK/dependency receipts, MCP before/after restart readback, systemd snapshots,
ledger counts and inspected browser screenshots. Installation is not live acceptance.

## Live outcome and exact blockers

Read-only ledger inspection observed zero connections, bindings, operations,
attempts and publications. **No live writes; no native operation/object IDs.**
Neither requested live lifecycle was executed:
preview -> publish -> readback; native schedule -> edit -> reschedule -> cancel.
Live custom emoji/media order/no duplicates/in-flight restart remain unverified.

Required inputs before live actions:

1. Owner-approved VibePublish Telegram credentials bundle: api_id, api_hash,
   StringSession session, placed in a private file/env, plus its authorized path
   or VIBEPUBLISH_* reference. No matching environment variables were present.
   EventsBot/other sessions were neither searched for nor used.
2. Exact numeric Telegram test-group ID for the supplied invite and channel ID
   for @lovekenig. The links are recorded authorization context, not guessed IDs.
   Channel schedule testing must remain at least 24 hours ahead; only newly
   created test objects should be edited/rescheduled/cancelled.
3. Exact VK community owner_id/group_id and approved role token bundle
   (editor, and reader/media as needed). No particular VK community was supplied.
4. Real Imagegen integration remains blocked by the missing process module and
   the owner's explicit prohibition on restoring/replacing it. Existing runbook
   also requires verified image-only isolation and bounded image-call budgets
   before activation; this run did not fabricate those attestations.
   Local Codex version: 0.153.0; model cache contains gpt-5.6-luna; imagegen skill
   exists. Cache/file presence is not a generation canary. No model generation
   was invoked, no fallback chosen, and actual image model remains unknown.
5. For direct remote/cloud MCP use, an authorized public TLS/auth ingress remains
   unconfigured. Loopback/IDE forwarding is the verified connection path.

On any uncertain provider outcome, do not resend; inspect/reconcile only.
