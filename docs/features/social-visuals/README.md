> Source/runtime evidence is tracked in [runtime delivery status](../../operations/social-runtime.md).
> The shared service, importer, compositor and optional new Codex adapter are
> delivered source; source availability alone does not prove host activation,
> live visual quality or acceptance of the policy change below.

# Social visuals

Owner requirements: `Fixed` from the 2026-09-04 handoff. Engineering choices: `Not confirmed by user`. Implementation: offline shared service `Not confirmed by user`; live executor and acceptance `Not done`.

Sources: `voice-20260904-165005-c0a0bcbe` and the binding correction in [the handoff](../social-operations/analysis-handoff-20260904.md). Publication/runtime/security rules live in [implementation design](../social-operations/implementation-design-v1.md).

## Product

Generate a new illustration, improve a rough/PIL-like card, or compose several sources into a publishable visual. Allow several candidates, automatic selection when explicitly authorized, human selection, reusable versioned presets and a clean preference corpus. Standalone creation and inline publication call the same VisualService.

Tuning means image-to-image improvement, not training the model. Real fine-tuning is future scope. Existing drafts are negative/rough inputs, not automatically positive training samples.

## Required executor

Owner clarification 2026-09-05: imagegen is an already used plugin/bundle, not
a hypothetical API or a requirement for an executable named `$imagegen`.
See [verified plugin sources and passive host inventory](../../reference/imagegen-plugin-discovery-20260905.md).
Codex built-in, explicit API-key fallback and an OpenCode package are distinct
execution paths. The researched OpenCode candidate is not yet identified as
the owner installation and hard-codes a different routing model; do not select
it silently. The actual VibePublish plugin-host binding remains **Not done**.

```text
VisualService -> ImagegenExecutor -> verified $imagegen route
requested route: gpt-5.6-luna
-> actual artifact import -> deterministic compositor -> validated candidates
```

Do not substitute Google Imagen/Gemini image APIs or assume the existing GoogleAIClient performs this job. The owner's earlier successful `$imagegen` experiment is a requirement/source fact, not a live test performed in this audit. Exact DevCoveer invocation, credentials, route availability and artifact return must be fresh-read during integration; no guessed CLI command is canonical.

The adapter contract is typed and independent of a general coding-agent workflow:

- `submit(job_key, mode, brief, source_manifest, preset_version, requested_route, candidate_budget, deadline)` returns a durable execution reference or a classified pre-dispatch error.
- `inspect(execution_ref)` returns queued/running/succeeded/failed/unknown, actual executor/model identity if supplied, bounded usage and artifact manifests.
- `find(job_key)` is a read-only durable-key lookup for a lost submit response; absence never authorizes automatic resubmission.
- `cancel(execution_ref)` is best effort, with actual outcome recorded; cancelling never claims already generated artifacts disappeared.
- Artifact manifests contain allowed-root file/object references, SHA-256, MIME, dimensions and size. The importer verifies actual bytes and ownership, not a model's textual assertion of success.

No shell fragments, arbitrary repository paths or raw model-selected commands come from the caller. Run the executor in a constrained workspace with only the job's source assets and output directory. A model cannot access social credentials or select publication targets. An uncertain submit is inspected using its durable identity, not submitted again automatically.

## Visual recipe and exact text

The art layer carries atmosphere/background/illustration. When optional exact editorial copy is supplied, Russian text, dates, venue names, addresses, logos and branded safe areas are composed deterministically from those structured fields using SVG/HTML/CSS or an equivalent layout engine. Presets own fonts, text overflow rules, safe zones, crops and allowed art treatments.

`4:5` and `9:16` are required output families. Text is reflowed for each family rather than cropped away. Source originals remain immutable. Resize/masks/metadata can use PIL; it is not the entire design system.

If a draft contains baked-in text, do not blindly draw new text over old generated lettering. Separate or reconstruct the art layer and validate the complete composite. Editorial facts must come from explicit user inputs or confirmed source extraction, not unchecked OCR. Facts ambiguous in a source produce a review blocker. Automated checks can establish dimensions, overflow, font/layout and supplied text; they cannot universally prove absence of accidental lettering or artistic quality. Initial presets and uncertain candidates retain an honest quality-review flag.
The owner's explicit execute-publication authorization below waives mandatory manual
selection for that delivery context, not artistic quality or exact-typography
verification.

## Candidate and approval semantics

Each job freezes mode, prompt/legacy brief, sources, preset version and cost budget.
Default 2 candidates, maximum 4. **Latest owner correction — 2026-09-05
(`Fixed`, implementation `Not confirmed by user`, live acceptance `Not done`):** an explicit
inline visual request attached to an execute publication authorizes automatic
selection of an eligible candidate without mandatory human selection. Omitted
delivery means **now**; `delivery.kind: now` is equivalent. A supplied future
`delivery.kind: at` means native scheduled publication, never a local timer or
fallback send-now. This supersedes the earlier future-queue-only restriction.
Explicit `selection: human` remains honored. Preview and standalone requests gain
no automatic publication authority. Actual destination/provider capabilities and
any separately imposed postponed-only acceptance boundary still apply.
Selection cannot substitute a different asset after approval.

For inline publishing, the selected final derivative becomes the **first** media item. Explicit `media` entries follow in their declared order. Visual source images are never published just because they were generation inputs. Story/media-count constraints are checked before any send. The preview enumerates exactly what will be attached.

Selection tokens bind tenant, job, parent publication, candidate hash, plan revision, surface, destinations, schedule and policy epoch. Replayed selection returns the existing result; stale/different selection fails CAS. Selection resumes the original publication only if its mode and original user authority permit execution. A preview-only publication remains awaiting approval. Schedule expiry, changed rights or changed editorial text blocks automatic resume.

Standalone selection produces an asset only; it cannot publish. Feedback changes the preference record, never an already published image. Re-generation creates another job/revision with a bounded new cost reservation.

## Prompt-first input (`Fixed` owner correction, acceptance `Not done`)

Use `prompt` for generation, tuning or composition. It is a compatible alias for
`brief`; legacy `brief` and optional structured `copy` keep working. Neither
structured copy nor manually split title/date/location fields are mandatory.
If both aliases are supplied they must match exactly. Quotes remain ordinary
prompt text and are forwarded unchanged; no OCR, fact extraction or guaranteed
exact typography is inferred from them. Structured copy, when explicitly supplied,
continues through the deterministic compositor; the executor request explicitly
asks for an art-only layer without lettering to avoid double overlay. Prompt-only lettering, if generated,
is unverified free text, not compositor-certified editorial content.

Generation optionally accepts 0–8 `sources` references; tune still requires one
`source`, and compose requires 2–8 `sources`. Explicit publication media without a
visual request are originals and must not call the generator. No new generator
model, API fallback or host activation is authorized by this input alias.

For example, `visual: {"kind":"generate","prompt":"Афиша с надписью \"Кто я?\""}`
needs no title/date/location extraction by the caller. Adding `sources` supplies
references, not publication attachments. Attach that visual to an execute
publication for immediate delivery, or add future `delivery.kind: at` for a native queue;
set `selection: human` to request manual choice instead.

## Provenance and permissions

Persist requested and actual executor identifiers separately, execution reference, prompt/preset version, source/output hashes, derivative recipe, candidate choice, feedback/rejection reason, editorial category and rights evidence. Missing actual executor metadata is recorded as unavailable, never fabricated from the requested route.

Tenant assets and feedback are excluded from shared training by default. Training permission is a separate owner/tenant-controlled policy, not an incidental MCP flag an agent can enable. Store consent scope, timestamp and version; support withdrawal for future dataset exports and delete eligible retained copies. Shared model training is not an automatic consequence of using the service.

Music/logos/photos supplied as sources need their own usage provenance; a model's approval does not establish rights.

## Initial acceptance fixtures

- https://t.me/kenigevents/4923
- https://t.me/lovekenig/12660

At implementation time fetch the authorized original media, not a screenshot of a guessed equivalent. Record source identity, exact extracted/confirmed editorial fields, multiple candidates and selected output. This audit did not download or generate these images.

Offline acceptance: fake executor success/failure/unknown/restart; path/MIME/hash checks; no cross-tenant candidate or preview access; exact source and selected lineage; no post on generation failure; single resume after replay; schedule expiry; text overflow; 4:5/9:16 safe regions; budget enforcement; consent defaults.

Live acceptance: actual `$imagegen` route on DevCoveer returns real verified artifacts through the required requested route; requested/actual identifiers are reported honestly; both fixtures have rendered human review; selected derivative is the one delivered; provider readback uses the evidence levels in the social design.


## Implemented checkpoint — 2026-09-05

`social_operations/visuals.py` is the sole service; `adapters/imagegen.py` defines
immutable typed requests/observations and an explicitly offline FakeImagegen.
Default wiring is unavailable. No real $imagegen, Google image provider or coding
agent was invoked. Requested route gpt-5.6-luna is stored separately from actual
executor/model metadata; a missing actual model remains null.

SQLite migration 1 -> 2 preserves core tables and adds immutable jobs/candidates,
private origins and append-only feedback. Core records a marker before submit,
then recovers lost responses by read-only job-key lookup, including after a real
worker-process exit. A frozen candidate budget is not an external billing quote.
The limit counts final candidates across formats (default 2, maximum 4); the art
request budget is rounded up by format count and no extra derivative is admitted.

Artifact imports are scoped to the exact job output directory. Traversal, symlink
files/directories, shared hardlinks, wrong SHA/MIME/size/dimensions and cross-job
artifacts are rejected. Actual verified art and final bytes are private immutable
assets. Rendering and metadata insertion are quota-bounded and transactional.

`social_operations/compositor.py` owns editorial-card-v1: 1080x1350 and 1080x1920,
SVG layout with explicit structured copy, safe regions and readable fixed glyph
outlines. It reads trusted DejaVu font files, stores their hashes, and does not
redistribute font files. CairoSVG renders the generated SVG. Unknown glyphs,
control characters and overflow block output rather than silently losing words.
Pillow only verifies inputs/derivatives and generates clearly synthetic test art.

Selection binds actor/job/plan/candidate hash through the frozen job digest and a
private one-use token, with CAS and current rights/routing/time checks. Inline
selection creates the first immutable provider attempts for the SAME original
operation. It never turns preview into execute. Standalone selection returns an
asset only. Private bytes are available by authenticated HTTP or MCP resource;
revocation invalidates reads, status and later asset reuse. Offline fixtures
cannot be published via native connections; CLI rejects --native plus --fake-imagegen.

### Explicit remaining gates

Real imagegen integration, verified originals of the two acceptance links above,
baked-in lettering/art quality, owner review of the initial preset, multiple
versioned brand presets and native-media canaries are not verified. Automatic
selection follows the owner-authorized explicit execute-publication exception above;
other real initial-preset contexts remain manual. This policy change is not proof
of artistic quality, exact prompt typography or live acceptance. Public asset ingress, policy-controlled training consent/withdrawal,
retention/export deletion and real feedback-dataset consumption remain Not done.
Consent defaults to shared_training=false; no training or export is performed.

Use the runtime runbook for exact execution evidence and the remote write blocker.


## Local Codex on DevCoveer: bounded process continuation

The optional [DevCoveer process executor](../../operations/devcoveer-imagegen.md)
now implements the existing typed executor and passes exact returned, verified
job-scoped files into the existing importer. Defaults remain disabled. Scripted
CLI subprocess tests are not a host/canary claim. The real installed version,
image-only enforcement and billed-call budget require operator verification;
actual image-model metadata stays unknown. No coding agent implemented this code.


## Owner-policy implementation checkpoint — 2026-09-05

Requirements above are owner-approved (`Fixed`); implementation/offline checks
are `Not confirmed by user`; live generation and queue acceptance of this change
remain `Not done` here. No provider, model or host configuration was called or
changed by this implementation lane.

`prompt` is normalized to `brief` before standalone/publication idempotency,
including equal dual aliases; differing aliases fail before admission. Native
execute defaults are derived only from frozen native publication plans; omitted time is immediate.
All initial real candidates keep `requires_review=true` as an honest unverified
quality indicator; owner-authorized execute selection may proceed despite
that indicator. It does not certify artwork or lettering. Candidate provenance
separates `prompt_text_unverified` from `explicit_copy_compositor_only`.

The existing selection transaction still verifies authority, source/output hashes,
format, schedule lead time, revision/token CAS, native fixture prohibition and
single parent continuation. Automatic immediate publication cannot extend an
expired command. Native account authority is checked separately from fixture
behavior. Existing explicit fixture standalone/preview selection remains harmless:
standalone creates no publication and preview still requires publication approval.
Ordinary media without visual bypasses VisualService and never calls Imagegen.

New offline native-shaped provider regressions exercise all three modes, optional
generation references, prompt/copy compatibility, exact selected-first media,
idempotency/CAS, explicit human preference, no authority elevation, expiry,
revocation, routing/revision changes, unknown generation and fixture fencing.
These simulated artifacts and provider updates are not live acceptance evidence.


### Immediate execute correction — 2026-09-05

The latest owner decision explicitly supersedes this document's former
future-schedule-only automatic-selection restriction. An authorized native
execute publication with explicit visual input may select and publish immediately
when delivery is omitted or `now`. Future `at` remains a native queue request.
The policy uses the same frozen parent plans, current rights checks, candidate
hash/token/revision CAS and exact-once continuation. An automatically selected
immediate result cannot renew an already expired original command deadline.

Offline regressions now cover immediate generation and tuning, omitted-time versus
explicit-now replay, immediate unknown outcomes and revocation/routing/revision/
expiry guards, alongside scheduled and human/preview/standalone cases. This change
does not grant provider capabilities: a deployment's VK postponed-only acceptance
wrapper still rejects immediate VK actions. No live calls or wrapper changes were
made by this code lane. Live acceptance and timezone configuration are tracked by
the integrator.
