# Imagegen plugin: verified sources and remaining host binding

Date: 2026-09-05. Owner requirement: **Fixed**. VibePublish host binding: **Not done**.
The owner reports successful imagegen use in Codex and connection to local OpenCode.
That history is not disproved by missing tools in a different ChatGPT session.
`$imagegen` was a user-facing hint, not a requirement for an executable of that name.

## Confirmed upstream identities

**Codex imagegen bundle.** Official `openai/skills` at
`49f948faa9258a0c61caceaf225e179651397431`,
`skills/.system/imagegen/SKILL.md`, defines built-in `image_gen` as the normal
route, with no OPENAI_API_KEY requirement. The separate Python CLI/API-key mode
is explicit-only, not an automatic fallback. The skill installs as a file bundle;
its presence alone does not prove the tool is exposed in the active session.

Source: https://github.com/openai/skills/blob/49f948faa9258a0c61caceaf225e179651397431/skills/.system/imagegen/SKILL.md

The actual current Codex implementation at `openai/codex`
`218e8df92683fee5d052fdde3d8e502f951227d7`,
`codex-rs/ext/image-generation/src/tool.rs`, exposes `image_gen.imagegen`.
The inspected argument struct accepts `prompt`, optional `referenced_image_paths`
(maximum five), and optional `num_last_images_to_include` (one to five).
It does not accept a model slug, output path, quality, size or arbitrary CLI flags.
The implementation records completed/failed image events and a saved path.
This source snapshot is NOT proof of the owner's installed Codex version.
Avoid ambient last-images selection in multi-tenant VibePublish: use explicit,
job-scoped verified sources through a host whose actual schema supports them.

Source: https://github.com/openai/codex/blob/218e8df92683fee5d052fdde3d8e502f951227d7/codex-rs/ext/image-generation/src/tool.rs

**OpenCode candidate, not identified as the owner's installed package.**
`yuji-hatakeyama/opencode-gpt-imagegen` at
`3a6338ff5bef6b6228818cba0b31818f2c2c8da8`; package `opencode-gpt-imagegen@0.1.12`.
It exports a PluginModule with id `opencode-gpt-imagegen` and tool `gpt_imagegen`.
Arguments: prompt, out, quality, optional size and images. Result: output text plus
metadata.out, metadata.versioned and metadata.billing. One call returns one PNG.
The implementation uses OpenCode ChatGPT OAuth and a single hosted
image_generation request. It is a third-party plugin, not an official OpenAI SDK.

Sources:
- https://github.com/yuji-hatakeyama/opencode-gpt-imagegen/blob/3a6338ff5bef6b6228818cba0b31818f2c2c8da8/src/index.ts
- https://github.com/yuji-hatakeyama/opencode-gpt-imagegen/blob/3a6338ff5bef6b6228818cba0b31818f2c2c8da8/package.json
- https://github.com/yuji-hatakeyama/opencode-gpt-imagegen/blob/3a6338ff5bef6b6228818cba0b31818f2c2c8da8/src/codex.ts

The candidate's subscription routing model is hard-coded to `gpt-5.5`, while the
VibePublish requested route is `gpt-5.6-luna`. Its tool has no model parameter.
Do not silently route through it and claim Luna execution. Its result does not
prove the actual image model. Preserve requested route, configured backend route,
and provider-reported actual model as different facts; unavailable metadata stays
unknown. No candidate installation, auth access or generation was performed here.

OpenCode documents config plugins at ~/.config/opencode/opencode.json and project
opencode.json, npm cache ~/.cache/opencode/node_modules, and local plugins in
~/.config/opencode/plugins and .opencode/plugins. Source:
https://opencode.ai/docs/plugins/

## Executable passive inventory

Run on the actual host, not on an unrelated ChatGPT container:

```bash
python scripts/inspect/probe_imagegen_plugin.py --project /path/to/vibepublish
```

It inspects bounded metadata only: Codex imagegen skill hashes, JSON/JSONC plugin
registrations, the researched candidate's package/version/repository metadata,
and hashes/tool-symbol hints of local JS/TS plugins. It never reads auth.json,
imports plugins, executes shell commands, installs packages or contacts models.
Secret values, arbitrary config payloads and credential-bearing URLs are not
emitted. Symlinks, hardlinks, nonregular and oversized files are refused.
Tests: `python -m pytest tests/inspection -q` (21 passed locally).

A manifest is `manifest_only_not_loaded`; a config is `configuration_only`;
a source match is `lexical_only_not_loaded`. `tool_callable` remains `not_probed`
and `owner_installation_identity` remains `not_verified`. This is deliberate:
a local file cannot prove the host currently exposes a callable tool.
The current ChatGPT container has neither the owner's Codex skill nor local
OpenCode configuration; that observation concerns this host only.

## Integration delta, not a new runtime

Keep the existing ImagegenExecutor, VisualService, immutable lineage, selected
hash, CAS and single parent continuation. Bind only after obtaining the actual
host package/version and runtime tool schema. No general coding-agent task is
needed to execute an image-only plugin call. Do not invent a direct OpenCode HTTP
tool-execution endpoint or assume a Codex built-in is an ordinary MCP server.
The actual host bridge is still not connected to VibePublish in this batch.

On ambiguous submission, preserve the core dispatch marker and outcome_unknown;
upstream gpt_imagegen has no durable job lookup/cancel/idempotency interface.
A timeout is not proof that no image was generated. Copy only verified job-scoped
returned artifacts into the existing importer; never scan generated_images for
an unrelated most-recent file. No Google/API-key substitute and no fake-as-live.

## GitHub write diagnosis

GitHub repository metadata reports push permission; the ChatGPT GitHub plugin
allows all actions. A previous core tree call returned: "Этот вызов инструмента
был заблокирован OpenAI, поскольку мы не смогли определить статус безопасности
запроса." That was not a GitHub 401/403, branch protection response, or proof of
unsafe code. The exact security-check cause is not exposed. Do not speculate
that file size, a particular string or missing OAuth caused it.

The new MAX handoff was written and read back at commit
`c18a2e14e1329e0d4487240db963fa3e32d57bf2`. Therefore the connection is not globally
read-only. This new bounded documentation/inventory work is not a retry or an
alternative encoding of the protected core payload. The full core/native/visual
archive remains separate from remote delivery; do not force-apply its seed-based
patch over these newer docs. Read current HEAD and transfer missing deltas only.
