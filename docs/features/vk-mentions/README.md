# VK Human-Readable Mentions

> Status: `Fixed` — implementation complete, regression tests passing.

## Overview

VK supports human-readable mentions using the markup format:
- Communities: `[club<id>|Display Name]` (e.g., `[club241261191|Полюбить Калининград]`)
- Persons: `[id<id>|Display Name]` (e.g., `[id123456789|Иван Петров]`)

VibePublish now integrates with the **canonical VK entity registry** (shared with events-bot) to resolve validated mentions at compile time, rendering frozen VK markup directly into the post text. Unverified registry candidates are never injected.

## Canonical Registry

- **Remote source**: `https://raw.githubusercontent.com/onedayonemasterpiece/idea-hub/chatgpt/vk-mentions-20261009/registry/vk-mentions/registry-v1.json`
- **Local cache**: Bounded TTL (24h) at `$VIBEPUBLISH_CACHE_DIR/vk_mentions_registry.json`
- **Stale fallback**: If remote fetch fails, stale local cache is used (no expiry enforcement)
- **Schema**: Array of entries with `target_ref`, `type` (`club`|`id`), `numeric_id`, `display_name`, `verified` (boolean)

## Compile-Time Resolution

When publishing to VK (`provider: "vk"`), semantic `mention` runs in paragraph content are resolved:

```json
{
  "paragraphs": [[
    {"kind": "text", "text": "Hello "},
    {"kind": "mention", "target_ref": "lovekenig", "label": "Полюбить Калининград"},
    {"kind": "text", "text": "!"}
  ]]
}
```

→ Compiles to plain text: `Hello [club241261191|Полюбить Калининград]!`

### Rules

- Only `provider: "vk"` accepts `mention` runs; Telegram/MAX raise `rich_fallback_needs_review`
- `target_ref` must exist in registry and be `verified: true`; unverified entries raise `vk_mention_unverified`
- Missing `target_ref` raises `vk_mention_not_found`
- Frozen markup is embedded in plain text; no native VK entities are used
- Compilation occurs **before** immutable plan/guid creation — the rendered text is part of the frozen intent

## Readback Equivalence (Critical Fix)

VK normalizes alternative mention syntax `@club<id> (Name)` / `@id<id> (Name)` to canonical `[club<id>|Name]` / `[id<id>|Name]` in stored post text.

**Before**: Exact text comparison caused `content_readback_mismatch` / `outcome_unknown` when user text contained both syntaxes.

**After**: Worker applies proven VK mention normalization to both expected and observed text before comparison:

```python
normalize_vk_mentions_for_comparison(text)  # @club123 (Name) → [club123|Name]
vk_mentions_equal(expected, observed)       # exact comparison after normalization
```

- Only proven VK normalization is applied (no generic stripping)
- Non-mention text compared exactly
- Preserves immutable idempotency — no retries of uncertain operations

## MCP Tools (Read-Only)

### `vibepublish_vk_mentions`

Scope: `destinations` (read-only)

#### Discover

```json
{"command": {"kind": "discover", "query": "kaliningrad", "limit": 50}}
```

Returns:
```json
{"mentions": [
  {"target_ref": "lovekenig", "type": "club", "numeric_id": 241261191,
   "display_name": "Полюбить Калининград", "verified": true}
]}
```

#### Validate

```json
{"command": {"kind": "validate", "target_ref": "lovekenig"}}
```

Returns:
```json
{"mentions": [{
  "target_ref": "lovekenig", "type": "club", "numeric_id": 241261191,
  "display_name": "Полюбить Калининград",
  "markup": "[club241261191|Полюбить Калининград]", "verified": true
}]}
```

## Regression Tests

Added in `tests/providers/test_vk_mentions.py`:
- Markup render: club and id types, multiple mentions
- Person/group distinction
- Stale/unverified candidate rejection
- Readback normalization: canonical↔alt syntax equivalence, exact non-mention comparison

## Files Changed

- `social_operations/vk_mentions.py` — registry loader, validation, normalization
- `social_operations/rich_text.py` — `mention` run kind handling for VK
- `adapters/vk.py` — imports normalization for readback
- `social_operations/worker.py` — VK mention equivalence in content readback
- `contracts/social_mcp_v1.py` — `vk_mentions` MCP tool schema
- `social_operations/service.py` — `vk_mentions` command handler
- `tests/providers/test_vk_mentions.py` — regression tests
- `docs/features/vk-mentions/README.md` — this document

## Verification

```bash
# Run VK mention tests
python -m pytest tests/providers/test_vk_mentions.py -v

# Full provider test suite
python -m pytest tests/providers/ -v

# Core integration tests
python -m pytest tests/providers/test_core_integration.py -v
```

All existing tests pass; no regressions introduced.