# Core terminal-unknown recovery: delivery checkpoint, 7 September 2026

**Status: source delivery Blocked; runtime integration Not done; not confirmed by owner.**
This is a factual checkpoint for existing **core PR #1**, not an executable recovery release, a replacement MAX task, or a declaration that MAX works.

Task: [owner-selected recovery handoff](https://github.com/onedayonemasterpiece/vibepublish/blob/1873bb1b5a8c5ad363919388d48e356197ebae42/docs/handoffs/max-core-recovery-completion-20260907.md). MAX remains in [PR #2](https://github.com/onedayonemasterpiece/vibepublish/pull/2).

## 1. The missing bytes were recovered without asking the owner to copy files

The actual `vibepublish-core-recovery-20260905.zip` was found in the owner's ChatGPT Library and read into this continuation. This is no longer merely context reconstructed from the [old author's report](https://github.com/onedayonemasterpiece/vibepublish/pull/1#issuecomment-5552197400).

- ZIP: **159087 bytes**, SHA-256 `a33fcd0654ba61fb774c1dbbeed6ae21d69761aad45c80685e9533106bcfc5cf`; all **42 manifest file hashes** match.
- The existing GitHub Actions artifact `9969726370` supplied a source archive and 70 pinned dependency wheels. Its source receipt is PR merge SHA `aaafbf52f03e79dbf7d4c19aeb669a01d791f677`; the reconstructed source tree is exactly `4c07f2ec2aee1530cc9bbdbcb4c5078be500d20d`, matching current core source [24c33d9e74efa6a28fa48ecb70287c60bca7ef5c](https://github.com/onedayonemasterpiece/vibepublish/tree/24c33d9e74efa6a28fa48ecb70287c60bca7ef5c).
- `git apply --check` and actual patch application reproduced all **27 changed paths**, byte-for-byte, and exact local tree `618df472a50557523678abc5e8eb3cc47d90937a`.
- Patch SHA-256: `4e3212a563e9f923957c650e1f53beb69eeca34547fa2b5d983b67907b3580f4`.
- Recovered port SHA-256: `308ea3d1c5a3aee1a5f8ccdf2053f14dbabe7347a30c5f6233fa17861676adc6`.

The historical local commit `564f76c0a5a4934fa1d37d4f6cea9e921670a1d9` is provenance, **not a delivered GitHub commit**. No old unreferenced intermediate tree was treated as a usable runtime.

## 2. New verification executed in this continuation

Python **3.13.5**, a fresh virtual environment, offline installation of all 70 hash-pinned wheels from the exact CI artifact, `pip check`, and editable installation succeeded.

| Check | Actual new result |
|---|---|
| `python -m pytest tests/recovery -q -ra --junitxml=...` | **48 passed in 11.96s**, zero failures/skips. Real local MCP ClientSession/HTTP, worker/SQLite, process-death/restart, observation-only recovery, exact compensation and post-commit release tests. Scripted providers, not live MAX. |
| `python -m pytest --collect-only -q` | **344 collected, 1 collection error, exit 2**: missing `adapters.codex_imagegen`. This is not full green. |
| All-tests diagnostic with `--continue-on-collection-errors` | Interrupted by the execution limit. A bounded verbose diagnostic was also interrupted; its last reported test was the existing runtime MCP transport test. Neither run is counted as completed or as 344 passed. |
| `python scripts/verify/telegram_sdk.py` | Real Telethon **1.44.0** / core compiler, **14 request kinds**, **zero network calls**. Not live Telegram evidence. |
| Compilation, `git diff --cached --check`, wheel build | Passed. The built wheel contains the exact recovered recovery module, port and migration 4. The wheel was not used to transfer blocked source. |

Local evidence hashes: recovery log `0007b1f8c7dbe082d6e8ccabdc61ec7d623fcaac6e2ee86d051f1a3ee8ca9503`; recovery JUnit `9a87188d11a4341b8c470b67957621ed077cf06ff1411d475900dcb18f829057`; strict collection log `92276bdb52cde0d672fd56f0dfe01b5a6a5e00f19918ce0ae7e34a425a7fab7c`.

No missing Imagegen implementation, stub, hidden skip, relaxed assertion, or weakened mandatory CI gate was introduced. The old author's 344 + 199 subtest result is historical, not a new result here.

## 3. Exact current delivery outcome

Normal `GitHub.create_tree` with the **complete recovered contents** of `adapters/port.py` and `social_operations/storage.py` was accepted, returning tree `a42d4c1cf8bb75531900936b622d8869c0720386`. Thus the old rejection of that request was not assumed to be permanent. A subsequent complete-content request for `social_operations/recovery.py` and `social_operations/recovery_schema.sql` was accepted as `9d564910d8e5ae8404bd8782ca5cb8419e4435e6`. Both trees match the independently reconstructed local file bytes.

An attempt to construct the full tree using locally verified blob identities returned ordinary GitHub **422**, `tree.sha 9fe2b6408cc9437408a85d1b39b097f7fef63d09 is not a valid blob`. That was an unavailable object, not a safety denial or a permission diagnosis.

The following ordinary `GitHub.create_tree` request containing the **complete recovered `social_operations/worker.py`**, based on the newly accepted tree, returned this **new current refusal** instead of a tree SHA:

> Этот вызов инструмента был заблокирован OpenAI, поскольку мы не смогли определить статус безопасности запроса.

The tool supplied no narrower cause. This is not a GitHub 401/403, proof that the file is malicious, or proof that every repository write is unavailable.

**Runtime delivery stopped at that boundary.** No different encoding, file split, alternate writer, CI job, MAX branch, another agent, or archive was used to deliver that denied worker payload. The accepted partial trees were not committed or attached to the core branch; they are incomplete and must not be consumed as a release. This document contains status and evidence metadata only, not the blocked payload.

## 4. What GitHub and MAX consumers can actually rely on

The runtime baseline remains [core source 24c33d9](https://github.com/onedayonemasterpiece/vibepublish/tree/24c33d9e74efa6a28fa48ecb70287c60bca7ef5c). Any commit adding this checkpoint is **documentation-only**; it does not provide migration 4, RecoveryService or the new executable interface on that branch.

Freshly read baseline [GitHub Actions run 33966897382](https://github.com/onedayonemasterpiece/vibepublish/actions/runs/33966897382) is **completed / failure**, on core head `24c33d9`. There is **no new remote recovery CI result**, because recovery source was not committed. Documentation CI cannot establish that the recovered implementation ran remotely.

The recovered local package does contain the previously described owner-only `inspect`, `compensate`, `release` commands, the existing eighth-tool boundary, migration 4, additive compensation/attribution port fields and post-commit finalization. These names are **not a substitute for delivery of actual code**. MAX must not infer a production port from this checkpoint or declare compensation capability without implementation and tests.

Existing MAX head at fresh read: `1873bb1b5a8c5ad363919388d48e356197ebae42`; runtime checkpoint `45d084d1d0e528cd04bd9e3e18e5ed39a495c6af`. This continuation changed no MAX source, live browser, session, original ledger, quarantine or social object. The original object's last reported live observation remains **5 September**; no new live observation or cleanup was performed here.

The same MAX task still owns its provider-specific writer/MCP wiring, exact attribution, compensation/finalize integration, edit/delete, media lifecycle and native scheduling. Not all those unfinished features are caused by core delivery. Original unknown must not be rewritten as success; no repeat Send or generic profile unlock is authorized by this checkpoint.

**Remaining blocker:** normal permitted delivery and verification of the complete same core patch in PR #1. The owner need not manually copy the recovered ZIP between windows. This checkpoint preserves the actual failure boundary instead of claiming that an archive, partial tree or documentation commit has delivered a working MAX product.
