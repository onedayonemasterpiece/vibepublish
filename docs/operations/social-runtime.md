# VibePublish runtime checkpoint

Status: **Not confirmed by user / partial remote delivery**. Do not deploy or
merge PR #1 as a complete application. There are no new live-provider claims.

## Current source delivery — 5 September 2026

Branch: `work/vibepublish-core-20260904`, existing PR #1.
The initial remote base was `73345b450793b92dfa1f3992713b4b7d7541c9b2`.
After the owner's request to check the access retrospective, actual standard
GitHub writes succeeded:

- `938f303d02230996b0c812d014ffa86124435452`: current domain vocabulary and
  emoji-compatible ProviderAdapter port, with branch readback.
- `348233a03b6d8dda3b70bd6fc3aea692bb2574b0`: the remaining accepted source
  checkpoint. Tree `9b3a9e6b416b866d0ecee492dc46f47b5a56fd37` exactly matches an
  independent local reconstruction from the remote base plus accepted files.

There are **26 changed/added files relative to the base**, not just comments:
SQLite storage and three migrations, Application, worker, MCP/HTTP server, CLI,
assets, provider port/helpers, native Telegram adapter/emoji metadata reads,
VK HTTPS transport and wiring, package metadata and the full-runtime CI gate.
These files are unchanged copies of the verified source archive. They do not
constitute a runnable full checkout: several imported modules, updated contracts,
skill and test suites have not been delivered. A successful tree response alone
was not treated as a commit; accepted objects were committed and the ref updated.

## New observed block, not an assumed permanent ban

Two later **distinct** source requests through the same `GitHub.create_tree`
action failed before returning a new tree SHA: `adapters/vk.py`, then the
independent `social_operations/rich_text.py`. Both returned exactly:

> Этот вызов инструмента был заблокирован OpenAI, поскольку мы не смогли определить статус безопасности запроса.

This is a current request-safety-evaluation block, not a GitHub 401/403 and not
missing write schemas. The actual reason is unavailable. Neither denied file
was subsequently uploaded by another route or encoding. The accepted checkpoint
does not contain their payloads. Later unattempted files are not falsely labelled
as individually denied. In total, **48 archive paths still differ or are absent**
relative to the complete source snapshot.

The previous decision to treat an older per-call failure as a permanent ban and
skip a normal authorized write was overbroad. Reading the idea-hub retrospective
and performing the write corrected that mistake and produced the commits above.
The new failures do not establish permanent loss of repository authorization;
current per-call safety decisions still must be respected. See the concise
[delivery proof rule](repository-workflow.md#proof-of-github-delivery).

## Complete local source and evidence boundaries

The complete source remains in `vibepublish-sdk-locked-20260905.zip`:
1,474,253 bytes, SHA-256
`179b101877e10c8d37606a4156a4de35e19cda6f127a26181553537623a5c40c`.
All **203 payload hashes and 133 source hashes** were verified in this turn.
Full LOCAL HEAD `8dcc771848051dab8b9bc7ae51f92a9757dfa7ef`, tree
`c0321a0823ae2373ed2ea51d8740d0da58cbb7bb`. The remote partial tree is different.
No local commit is represented as remotely available merely by mentioning its SHA.

Earlier complete local evidence: 327 tests + 199 subtests, including real SDK
serialization and independent patch replay. Those tests were not rerun on this
incomplete remote tree and are not its acceptance evidence. The old green CI at
`73345b4` tested only delivered seed/tooling/SDK files. The preserved single
GitHub-hosted workflow now includes mandatory full-runtime checks; missing modules
must fail rather than be skipped or hidden by reinstating seed-only checks.

Telegram emoji/catalog/rules and DevCoveer Codex ImagegenExecutor exist in the
complete local snapshot; remote delivery remains incomplete. The executor stays
inactive until actual installed DevCoveer image-only host controls are verified.
No real image generation, model task, provider session, publication or deployment
was run in this delivery turn. MAX development remains separate in PR #2; no
MAX files or live task were changed or launched.

## Continuation scope

Preserve the existing complete implementation and PRs. Do not reimplement from
the incomplete remote seed. Once authorized source delivery is actually possible,
reconcile against the current branch and require exact full-source readback,
full hosted runtime CI, and the still-separate live/host capability gates.
The historical design and archive handoffs describe earlier checkpoints; this
file is the current remote-delivery status.
