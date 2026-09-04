# MCP contract v1 — selected implementation design

Version: `1.0.0-design`. Status: `Not confirmed by user`. Runtime: `Not done`.

Canonical schemas: [`contracts/social_mcp_v1.py`](../../../contracts/social_mcp_v1.py). Golden tasks: [`contracts/task_corpus_v1.py`](../../../contracts/task_corpus_v1.py). These are executable design artifacts, not a running MCP server. The [implementation design](implementation-design-v1.md) owns runtime semantics; this document owns model-facing grammar.

## 1. Taxonomy decision

The optimization target is correct task completion with few calls and little irrelevant context, not the smallest possible tool count.

| Candidate | Structural result on the task inventory | Decision |
|---|---|---|
| Six generic methods (`get_started/publish/publication/visual/read/operation`) | Engagement and destination management have no distinct home unless read becomes mutating or operation becomes a generic command router; short names hide complex discriminators | Rejected as the canonical starting point |
| Eight task-oriented methods below | Separates new content, existing publication, visual production, observation, provider reading, engagement and destination configuration; primary publisher sees only five | Selected for implementation |
| Twelve or more split/convenience methods | Separate tools for schedule/story/video/analytics/selection offer multiple routes to the same job and duplicate schemas | Rejected until a measured usability benefit justifies a split |

This is an explicit design comparison, **not an A/B model benchmark**. No invalid-call percentages or optimality claims are inferred from hand-authored golden calls. Real weak-agent evaluation remains a release gate.

| Method | Owns | Does not own |
|---|---|---|
| `vibepublish_get_started` | Versioned skill, allowed aliases/sets, capabilities and tenant time context | Grant creation, secrets or provider login |
| `vibepublish_publish` | One new publication, optional inline visual, immediate/scheduled/preview | Editing an existing post, raw SDK operations |
| `vibepublish_publication_update` | Approve, edit, reschedule, cancel, delete, safe failed-child retry | New publication, blind retry or implicit delete on cancel |
| `vibepublish_visual` | Standalone generate/tune/compose, select, feedback | Independent publication after standalone generation |
| `vibepublish_status` | Local owned operation/publication/visual receipts and recent operations | Provider feed reads, retries or forced send |
| `vibepublish_read` | Exact items, dialogs, feeds/search, comments/reactions, stories, scheduled queue, notifications, editorial samples and analytics | Social mutation |
| `vibepublish_engage` | Reply, react/remove reaction, forward/repost | Provider credential administration |
| `vibepublish_destinations` | List/resolve/search, create/update/delete sets, rename display labels | Ownership verification by URL alone, granting access or changing stable native identity |

The five-tool publisher projection is get_started, publish, publication_update, visual, status. The other tools require corresponding grants. Owner-only connection/principal administration is initially CLI, not a hidden arbitrary MCP command. `required_scope` in the design generator is internal metadata; `project_catalog` removes it from wire tool definitions. Actual handlers still enforce operation-level scopes and resource bindings even when a client directly invokes a hidden tool.

## 2. Common grammar

All schemas have an object root, explicit properties and closed objects. Tagged commands use `kind`. Every tool's `$defs` is self-contained and includes only reachable definitions. Do not send Python helper metadata or unresolved references across the MCP wire.

Service IDs and aliases are opaque strings, not native Telegram/VK/MAX IDs. The server supplies existing IDs, revisions and tokens; the model never invents them. Normal publication uses `to` aliases only. New/ambiguous destinations go through authorized resolution or owner onboarding before publishing.

Defaults selected for implementation:

| Field | Default / semantics |
|---|---|
| `surface` | `post`; channel/wall distinction follows the destination; `message` covers a bound direct or Saved Messages target |
| `mode` | `execute` only within the authenticated user's authority and application approval policy; preview never sends |
| `delivery` | `{kind: now}`; scheduled input requires a timestamp with UTC offset |
| scheduled `backend`, `late` | `service`, `hold`; native scheduling requires an explicitly proven capability |
| `content.format` | `plain`; optional bounded Markdown subset, not provider-native escaping |
| `media.role` | `auto`, derived from verified MIME/geometry; incompatible requested role is rejected |
| visual `candidates`, `selection` | 2, human; automatic selection must be explicitly requested/authorized |
| visual `formats` | post_4_5 and story_9_16; the publication surface chooses the corresponding accepted derivative |
| visual `copy` | No overlaid editorial text when absent. Exact title/subtitle/body/date/location/source strings are supplied separately from the art brief |
| `limit` | 20, maximum 50; cursors are opaque and bound to principal, query and policy epoch |

Preset names must come from configured tenant presets. An absent preset resolves to the tenant's versioned default; unavailable defaults fail explicitly. Brand/logo/font choices belong to that preset, not to a model-provided filesystem path. Inline visual output is the first attachment, then explicit media in order; generation sources are not automatically attachments.

Empty text is permitted structurally because editing a caption to empty is legitimate. Runtime validation must reject a resulting publication with no meaningful text and no deliverable media. Whitespace-only text, media capacity, calendar validity, expiry, URL safety, grant intersection and unsupported capabilities are semantic checks, not purported guarantees of JSON Schema alone.

`expected_revision` is required for publication edits and set updates. `set_put` is explicit full replacement: revision 0 creates a previously nonexistent set, otherwise exact current revision is required. Members must be concrete already-authorized destinations; no nested sets. `rename_label` changes the display name, not the stable alias. Mutating an alias's meaning to redirect already accepted work is forbidden.

The current grammar covers the first working publishing slice and the principal donor operation families. Exotic provider-native options, polls or every historical formatting construct are **not silently claimed implemented**. Before exposing such a donor capability, add its exact typed fields, input/output fixtures and adapter tests under the existing task method. No `options: any`, raw provider method, new synonym tool or global lowest-common-denominator switch is allowed.

## 3. Responses, timeouts and transport

Successful mutations return a durable receipt with `operation_id`, `action`, `state`, `next_action`, `retry_safe`, `receipt_ref` and `deliveries`. `resource_id` is the publication or visual resource as appropriate. For updates, use the returned current revision. Visual candidates include owned asset references and output hashes. Review tokens are short-lived, single-use and scope-bound; do not put them in URLs or ordinary logs.

Before acceptance, a closed error response contains `error.code/message/field`, `message`, one `next_action` and `retry_safe: false`, **without fabricating an operation ID**. After acceptance, failures/uncertainty remain on the original receipt. The MCP adapter uses `isError` for tool execution errors and emits structured content conforming to the error branch; syntactically malformed RPCs use protocol errors. One-call success means one mutation request, not a promise that every provider finishes before the tool timeout.

Persist first, return within the request budget, and let the worker continue. Status polling respects `poll_after_seconds`; status itself never retries or mutates the provider. Application status is independent of any MCP experimental task mechanism or client connection lifetime.

| Condition | Error/state | Next action |
|---|---|---|
| Invalid fields/time/media | invalid_input, media_unavailable | fix_input |
| Alias unknown or bootstrap stale | destination_unknown, stale_context | refresh |
| Grant denied | access_denied | contact_owner |
| Expired connection | needs_auth | reauthorize |
| Revision or outside edit conflict | revision_conflict, external_change | refresh |
| Existing key with different request | idempotency_conflict | fix_input; never create a replacement send automatically |
| Waiting for human | needs_approval / needs_selection | approve / select_visual |
| Accepted work still running | queued / running | check_status |
| Possible remote effect without proof | outcome_unknown | review_outcome; retry_safe=false |
| Partial fan-out | partial | inspect child receipts; retry only server-proven failed children |

A rejected unchanged request is not made safe by retrying it. `fix_input` authorizes correction of arguments, not publication to a different destination. Capabilities are runtime observations, not permissions.

HTTP projection: POST `/v1/publications`, POST `/v1/publications/{id}/commands`, POST `/v1/visuals/commands`, POST `/v1/engagement/commands`, POST `/v1/destinations/commands`, POST `/v1/reads`, GET `/v1/operations/{id}` and GET `/v1/bootstrap`. These endpoints call the same services and schemas, with path IDs mapped deterministically. Mutating service clients supply an Idempotency-Key. HTTP 202 means accepted, not published; 409 covers conflicts; 422 invalid input; 403 denied; 429 quota. Accepted provider uncertainty is returned as a receipt, not a generic retriable 500.

## 4. Bootstrap and skill

Canonical text: [`docs/llm/vibepublish-social-skill.md`](../../llm/vibepublish-social-skill.md). Serve it as a versioned MCP resource/prompt and through get_started. Proposed resource URI: `vibepublish://skills/social/1.0.0-design`. Keep the fallback tool; do not assume every client supports resources/prompts.

Compute SHA-256 from canonical UTF-8 skill bytes. `if_version` is a cache hint, never an authorization shortcut. Responses still contain current granted context. First page should contain the primary task-relevant aliases, a compact capability summary and examples, not every channel or conversation. Proposed core skill budget <=1500 tokens before destination context, measured with the target client's tokenizer at integration. `estimated_tokens` is explicitly an estimate, not billed usage. This audit measured JSON bytes, not model token counts.

Cache key: authenticated principal + policy epoch + skill/schema version; capability entries include observation time. Revocation invalidates stale authorization even if the model retained the old skill. A model can still call with old context; the server remains authoritative.

## 5. Executed offline checks

Command run in the local analysis environment on 2026-09-04:

```bash
python -m pip install -r contracts/requirements.txt
python tests/contracts/test_social_mcp_design.py
python contracts/social_mcp_v1.py > social-mcp.v1.generated.json
python contracts/task_corpus_v1.py > task-corpus.v1.generated.json
```

The validator dependency was already available locally (`jsonschema` 4.26.0); installation is shown for reproduction, not claimed executed here.

Result: **8 test methods passed**, validating **16 schemas**, **80 golden calls** across all eight tools and **20 negative calls**. Checks also cover closed object shapes, success/error response examples, finite next_action, deterministic generation and the five-tool grant projection. Deliberately forbidden but syntactically valid jobs carry runtime-oracle labels; this run does not pretend that an absent server enforced those labels.

Compact input schema byte counts after explicit visual-copy fields:

```text
get_started             324
publish                6284
publication_update     4538
visual                 4332
status                  379
read                   3136
engage                 2644
destinations           1959
```

Total: 23,596 UTF-8 bytes of compact input schemas. The five-tool publisher input schema total is 15,857 bytes. Descriptions, output schemas and runtime skill/context are additional; these figures are not total context size or measured token cost. Generated JSON is a build artifact; the Python schema definition remains canonical.

Not run: a live weak model, real MCP client compatibility, provider/browser flows, database concurrency or the existing Google gateway suite. This audit uses no external model executor.

## 6. Required weak-agent benchmark

Before publishing the MCP server, run the same task corpus through a genuinely weak available model with exact model/build/prompt/tokenizer recorded. Add paraphrases, missing information, stale receipts, malicious provider text and tool/schema distractors. Execute calls only against a deterministic fake server with explicit authority fixtures, not real channels.

Compare six/eight/split variants with the same source tasks and budgets; count correct method, schema-valid arguments, exact destination/media/schedule, unauthorized attempts, improper unknown-outcome retries, mutation-call count and token cost separately. Publish the real confusion matrix and saved calls. A hand-authored expected-tool matrix is not a measured confusion matrix.

Proposed acceptance: >=98% schema-valid first calls, >=95% correct benign tasks without repair, 100% correct final target/media/schedule after at most one permitted repair, zero executed unauthorized effects and zero duplicate effects under adversarial/restart tests. Unsafe attempted calls are reported even if the server blocks them. Thresholds are release criteria, not achieved results. Failures change descriptions/arguments first; method count is not protected from evidence-based correction.
