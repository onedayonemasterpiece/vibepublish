> Historical archive handoff, not current branch status. Read
> [the current continuation](core-emoji-imagegen-continuation-20260905.md)
> and [runtime delivery status](../operations/social-runtime.md) first.
> Versions, counts and limitations below describe that earlier checkpoint.

# Continue VibePublish: deliver the tested native/visual patch

Work directly in ChatGPT/GitHub and local execution, not Codex/other agents.
Do not rewrite the existing core. MAX, imagegen/social canaries and deployment
are NOT authorized by this handoff.

Repository onedayonemasterpiece/vibepublish, existing branch
work/vibepublish-core-20260904, draft PR #1. Last read-back remote HEAD:
60712c41cee5975c24c4e5346b22857f39c035ec; main:
1ceb1cee2acd867c88f6e94a2815e78e816374fa. Fresh-read these again and preserve
concurrent changes. No reset/force-push or other branch/runtime.

The delivery archive contains the FULL cumulative patch, source snapshot,
per-commit patches, MANIFEST.json and verification evidence. It supersedes the
old core-only archive. The GitHub tree call was blocked by OpenAI before commit;
one unreferenced partial tree is not branch delivery. Do not bypass the guard.
Local commits and remote commits must be reported separately.

## One next package

After an authorized write path is available, verify the archive hashes and apply
only missing changes to the current branch. At the exact base, use git apply
--check first. At an advanced head, inspect the delta and resolve conflicts; never
replace the repository by the archive wholesale. Keep source/tests/canonical docs
and CHANGELOG together, excluding temporary artifacts and evidence.

Run python -m pip install -r requirements.lock, then
python -m pip install --no-deps --no-build-isolation -e .,
python -m pytest tests -q and compileall. The one GitHub-hosted CI workflow also
installs libcairo2/fonts-dejavu-core; no self-hosted runner. Read back the remote
commit SHA and key files, inspect the actual full CI result and update PR #1.
Do not claim success from a local commit or a successful call without readback.
If protection still blocks writes, stop the write attempt, keep an applicable
patch and diagnose the real limitation rather than encoding/chunking around it.

## What is already implemented

Read docs/operations/social-runtime.md, docs/reference/native-adapter-provenance.md,
canonical social-operations/social-visuals docs, skill and routes. Core native-only
schedule ledger + concrete TG/VK adapters/transport fixtures + existing-item CAS
+ one inline/standalone VisualService with typed fake ImagegenExecutor and SVG
compositor. Eight MCP methods and HTTP/private-resource parity. Final offline
suite: 168 methods plus 199 subtests, zero failures or skips; see actual archive
logs for exact commands and the separate clean-base patch replay.

Full clean lock install is still unverified: local package-index access failed;
36/55 lock versions match the available test environment. Telethon SDK is not
installed locally. Fake/scripted success is not a provider/model canary.

Shared MAX interface is adapters/port.py. Latest port change is LOCAL commit
25de851b911d02fc9ece2a7e193743758bfa48c1, including native_target,
provider_media and member_ids. The remote seed is an older port. No MAX driver
exists in this work; do not duplicate it. Honor awaited progress/checkpoint/
before_effect and core-owned dispatch/auth/ledger.

Remaining product gates are enumerated exactly in the canonical runbook and
native/visual docs: do not remove stories/video/rich content/discovery/analytics
or infer scheduled VK repost. Initial nonfixture visual presets require human
review; real imagegen and original visual acceptance fixtures were not run.
