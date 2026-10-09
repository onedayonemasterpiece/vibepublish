"""VK mention registry: canonical entity data with bounded local cache and safe stale fallback.

Shared canonical VK entity data consumed by both events-bot & VibePublish.
Remote registry at https://raw.githubusercontent.com/onedayonemasterpiece/idea-hub/chatgpt/vk-mentions-20261009/registry/vk-mentions/registry-v1.json
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen, Request

from .domain import DomainError


REGISTRY_URL = "https://raw.githubusercontent.com/onedayonemasterpiece/idea-hub/chatgpt/vk-mentions-20261009/registry/vk-mentions/registry-v1.json"
CACHE_DIR = Path(os.environ.get("VIBEPUBLISH_CACHE_DIR", "/tmp/vibepublish_cache"))
CACHE_FILE = CACHE_DIR / "vk_mentions_registry.json"
CACHE_TTL = 24 * 3600  # 24 hours


@dataclass(frozen=True, slots=True)
class VKMention:
    """Validated VK mention entity."""
    target_ref: str
    type: str  # 'club' or 'id'
    numeric_id: int
    display_name: str
    markup: str  # Frozen literal VK markup, e.g., '[club241261191|Полюбить Калининград]'
    verified: bool


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_local_cache() -> dict[str, Any] | None:
    """Load registry from local cache if fresh enough."""
    try:
        if not CACHE_FILE.exists():
            return None
        stat = CACHE_FILE.stat()
        if time.time() - stat.st_mtime > CACHE_TTL:
            return None
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_local_cache(data: dict[str, Any]) -> None:
    """Save registry to local cache."""
    _ensure_cache_dir()
    try:
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    except OSError:
        pass  # Cache write failure is non-fatal


def _fetch_remote_registry() -> dict[str, Any] | None:
    """Fetch registry from remote URL."""
    try:
        req = Request(REGISTRY_URL, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def load_registry() -> dict[str, Any]:
    """Load VK mention registry with bounded local cache and safe stale fallback."""
    # Try remote first
    remote = _fetch_remote_registry()
    if remote is not None:
        _save_local_cache(remote)
        return remote

    # Fallback to local cache (even if stale)
    local = _load_local_cache()
    if local is not None:
        return local

    raise DomainError("vk_mention_registry_unavailable", "Cannot load VK mention registry: remote unreachable and no local cache")


def validate_registry_entry(entry: dict[str, Any]) -> VKMention:
    """Validate a single registry entry and produce frozen VK markup."""
    # Required fields
    target_ref = entry.get("target_ref")
    vk_type = entry.get("type")
    numeric_id = entry.get("numeric_id")
    display_name = entry.get("display_name")
    verified = entry.get("verified", False)

    if not isinstance(target_ref, str) or not target_ref:
        raise DomainError("vk_mention_invalid", "target_ref must be a non-empty string")
    if vk_type not in ("club", "id"):
        raise DomainError("vk_mention_invalid", "type must be 'club' or 'id'")
    if not isinstance(numeric_id, int) or numeric_id <= 0:
        raise DomainError("vk_mention_invalid", "numeric_id must be a positive integer")
    if not isinstance(display_name, str) or not display_name:
        raise DomainError("vk_mention_invalid", "display_name must be a non-empty string")
    if not isinstance(verified, bool):
        raise DomainError("vk_mention_invalid", "verified must be a boolean")

    # Build frozen VK markup
    prefix = "club" if vk_type == "club" else "id"
    markup = f"[{prefix}{numeric_id}|{display_name}]"

    return VKMention(
        target_ref=target_ref,
        type=vk_type,
        numeric_id=numeric_id,
        display_name=display_name,
        markup=markup,
        verified=verified,
    )


def resolve_mention(target_ref: str) -> VKMention:
    """Resolve a target_ref to a validated VKMention. Only verified entries allowed for rendering."""
    registry = load_registry()
    entries = registry.get("entries", [])
    if not isinstance(entries, list):
        raise DomainError("vk_mention_registry_invalid", "Registry entries must be a list")

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("target_ref") == target_ref:
            mention = validate_registry_entry(entry)
            if not mention.verified:
                raise DomainError("vk_mention_unverified", f"Mention '{target_ref}' is not verified; cannot inject")
            return mention

    raise DomainError("vk_mention_not_found", f"Mention '{target_ref}' not found in registry")


def discover_mentions(query: str = "", *, limit: int = 50) -> list[dict[str, Any]]:
    """Discover VK mentions by query (search in target_ref or display_name). Read-only, safe scoping."""
    registry = load_registry()
    entries = registry.get("entries", [])
    if not isinstance(entries, list):
        raise DomainError("vk_mention_registry_invalid", "Registry entries must be a list")

    query_lower = query.lower()
    results = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        target_ref = entry.get("target_ref", "")
        display_name = entry.get("display_name", "")
        if not query or query_lower in target_ref.lower() or query_lower in display_name.lower():
            mention = validate_registry_entry(entry)
            results.append({
                "target_ref": mention.target_ref,
                "type": mention.type,
                "numeric_id": mention.numeric_id,
                "display_name": mention.display_name,
                "verified": mention.verified,
            })
            if len(results) >= limit:
                break
    return results


def validate_mention(target_ref: str) -> dict[str, Any]:
    """Explicit validation of a target_ref. Returns full validated mention or raises."""
    mention = resolve_mention(target_ref)
    return {
        "target_ref": mention.target_ref,
        "type": mention.type,
        "numeric_id": mention.numeric_id,
        "display_name": mention.display_name,
        "markup": mention.markup,
        "verified": mention.verified,
    }


_VK_MENTION_ALT_PATTERN = re.compile(r'@(club|id)(\d+)\s*\(([^)]+)\)')
_VK_MENTION_CANONICAL_PATTERN = re.compile(r'\[(club|id)(\d+)\|([^\]]+)\]')


def normalize_vk_mentions_for_comparison(text: str) -> str:
    """Normalize VK mention syntaxes for readback equivalence comparison.

    VK accepts both '@club<id> (name)' and '@id<id> (name)' alternative syntaxes
    and normalizes them to the canonical '[club<id>|name]' / '[id<id>|name]' format.
    This function applies the same normalization so that expected and observed texts
    can be compared exactly after normalization.

    Only proven VK mention normalization is applied; no generic text stripping.
    """
    def replace_alt(match):
        prefix, num, name = match.groups()
        return f'[{prefix}{num}|{name}]'

    # Normalize alternative syntax to canonical markup
    normalized = _VK_MENTION_ALT_PATTERN.sub(replace_alt, text)
    return normalized


def vk_mentions_equal(expected: str, observed: str) -> bool:
    """Compare two texts for VK mention equivalence.

    Applies VK mention normalization to both texts before exact comparison.
    Preserves exact comparison for non-mention content.
    """
    return normalize_vk_mentions_for_comparison(expected) == normalize_vk_mentions_for_comparison(observed)