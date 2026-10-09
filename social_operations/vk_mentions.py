"""VK mention registry: canonical entity data with bounded local cache and safe stale fallback.

Shared canonical VK entity data consumed by both events-bot & VibePublish.
Remote registry at https://raw.githubusercontent.com/onedayonemasterpiece/idea-hub/chatgpt/vk-mentions-20261009/registry/vk-mentions/registry-v1.json
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen, Request

from .domain import DomainError


REGISTRY_URL = "https://raw.githubusercontent.com/onedayonemasterpiece/idea-hub/chatgpt/vk-mentions-20261009/registry/vk-mentions/registry-v1.json"
CACHE_DIR = Path(os.environ.get("VIBEPUBLISH_CACHE_DIR", "/tmp/vibepublish_cache"))
CACHE_FILE = CACHE_DIR / "vk_mentions_registry.json"
CACHE_TTL = 3600  # One hour of local reads without a remote request.
CACHE_STALE_MAX = 24 * 3600  # Bounded outage fallback only.


@dataclass(frozen=True, slots=True)
class VKMention:
    """Validated VK mention entity."""
    target_ref: str
    type: str  # 'club' or 'id'
    numeric_id: int | None
    display_name: str
    markup: str | None  # Frozen literal VK markup, e.g., '[club241261191|Полюбить Калининград]'
    verified: bool


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_local_cache(max_age: int = CACHE_TTL) -> dict[str, Any] | None:
    """Load registry from local cache if fresh enough."""
    try:
        if not CACHE_FILE.exists():
            return None
        stat = CACHE_FILE.stat()
        if time.time() - stat.st_mtime > max_age:
            return None
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_local_cache(data: dict[str, Any]) -> None:
    """Save registry to local cache."""
    _ensure_cache_dir()
    try:
        tmp = CACHE_FILE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(CACHE_FILE)
    except OSError:
        pass  # Cache write failure is non-fatal


def _fetch_remote_registry() -> dict[str, Any] | None:
    """Fetch registry from remote URL."""
    try:
        req = Request(REGISTRY_URL, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as response:
            if response.status != 200:
                return None
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                return None
            return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def load_registry() -> dict[str, Any]:
    """Load VK mention registry with bounded local cache and safe stale fallback."""
    # Avoid a network request on every publish or MCP search.
    fresh = _load_local_cache()
    if fresh is not None:
        return _validate_registry_root(fresh)

    remote = _fetch_remote_registry()
    if remote is not None:
        remote = _validate_registry_root(remote)
        _save_local_cache(remote)
        return remote

    # No indefinite trust of an old snapshot; each candidate proof is also
    # rechecked for age at resolution time.
    local = _load_local_cache(max_age=CACHE_STALE_MAX)
    if local is not None:
        return _validate_registry_root(local)
    raise DomainError("vk_mention_registry_unavailable", "No current or bounded cached VK mention registry")


def _validate_registry_root(data: dict[str, Any]) -> dict[str, Any]:
    """Accept only the current canonical IdeaHub wire contract or local v0 tests."""
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise DomainError("vk_mention_registry_invalid")
    if len(data["entries"]) > 500:
        raise DomainError("vk_mention_registry_invalid")
    if "schema_version" in data:
        if data["schema_version"] != 1:
            raise DomainError("vk_mention_registry_invalid")
        seen = set()
        for row in data["entries"]:
            if not isinstance(row, dict) or not isinstance(row.get("key"), str):
                raise DomainError("vk_mention_registry_invalid")
            if row["key"] in seen:
                raise DomainError("vk_mention_registry_invalid")
            seen.add(row["key"])
            validate_registry_entry(row)  # Prove wire safety before caching.
    return data


def _entry_ref(entry: dict[str, Any]) -> str:
    return entry.get("key") if "key" in entry else entry.get("target_ref", "")


def _entry_name(entry: dict[str, Any]) -> str:
    return entry.get("name") if "key" in entry else entry.get("display_name", "")


def validate_registry_entry(entry: dict[str, Any]) -> VKMention:
    """Validate a single registry entry and produce frozen VK markup."""
    # Required fields
    canonical = "key" in entry
    target_ref = _entry_ref(entry)
    display_name = _entry_name(entry)
    if canonical:
        entity_type = entry.get("entity_type")
        vk_type = {"community": "club", "person": "id"}.get(entity_type)
        numeric_id = entry.get("vk_id")
        status = entry.get("status")
        if status not in {"verified", "candidate"}:
            raise DomainError("vk_mention_invalid", "Invalid candidate verification status")
        verified = status == "verified"
        if verified:
            evidence = entry.get("evidence")
            verified_at = entry.get("verified_at")
            if (not isinstance(evidence, list) or not evidence
                    or not all(isinstance(x, str) and x.startswith("https://") for x in evidence)
                    or not isinstance(verified_at, str)):
                raise DomainError("vk_mention_invalid", "Verified VK ID requires current source evidence")
            try:
                age = time.time() - datetime.fromisoformat(
                    verified_at.replace("Z", "+00:00")
                ).astimezone(timezone.utc).timestamp()
            except (ValueError, OverflowError):
                raise DomainError("vk_mention_invalid", "Invalid verification timestamp") from None
            if age < -300 or age > 30 * 86400:
                verified = False  # Keep discoverable, never emit native mention.
    else:
        vk_type = entry.get("type")
        numeric_id = entry.get("numeric_id")
        verified = entry.get("verified", False)

    if not isinstance(target_ref, str) or not target_ref:
        raise DomainError("vk_mention_invalid", "target_ref must be a non-empty string")
    if vk_type not in ("club", "id"):
        raise DomainError("vk_mention_invalid", "type must be 'club' or 'id'")
    if (numeric_id is not None and (type(numeric_id) is not int or numeric_id <= 0)) or (verified and numeric_id is None):
        raise DomainError("vk_mention_invalid", "numeric_id must be a positive integer for verified entries")
    if not isinstance(display_name, str) or not display_name:
        raise DomainError("vk_mention_invalid", "display_name must be a non-empty string")
    if not isinstance(verified, bool):
        raise DomainError("vk_mention_invalid", "verified must be a boolean")

    # Build frozen VK markup
    prefix = "club" if vk_type == "club" else "id"
    if "|" in display_name or "[" in display_name or "]" in display_name:
        raise DomainError("vk_mention_invalid", "Unsafe mention label")
    markup = f"[{prefix}{numeric_id}|{display_name}]" if verified else None

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
        if _entry_ref(entry) == target_ref:
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
        target_ref = _entry_ref(entry)
        display_name = _entry_name(entry)
        aliases = entry.get("aliases") or []
        if not isinstance(target_ref, str) or not isinstance(display_name, str):
            continue
        if (not query or query_lower in target_ref.lower() or query_lower in display_name.lower()
                or any(isinstance(alias, str) and query_lower in alias.lower() for alias in aliases)):
            mention = validate_registry_entry(entry)
            results.append({
                "target_ref": mention.target_ref,
                "type": mention.type,
                "numeric_id": mention.numeric_id,
                "display_name": mention.display_name,
                "markup": mention.markup,
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