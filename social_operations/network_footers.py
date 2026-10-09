"""Owner publisher cross-network footers, compiled after rich text and before plans freeze.

The editorial model does not own this navigation. Route by bound destination alias,
resolve VK community IDs from the owner's live registry and keep semantic link
entities (not byte-matched Markdown) as the idempotency boundary.
"""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import urlsplit

from .domain import DomainError
from .rich_text import normalized_entities, utf16

# Source destination -> ordered (caption, verified target alias).
ROUTES = {
    "lovekenig_tg": (("ВКонтакте", "lovekenig_vk"),),
    "tg_74cd62f2688ba88ab5fd": (
        ("ВКонтакте", "vk_972b45c6f71c0f2a1fb9"),
        ("MAX", "max_lovekenig_announcements"),
    ),
    "tg_5060f37d74cf460135ee": (
        ("ВКонтакте", "vk_027d33367c33ba2599ee"),
        ("MAX", "max_lovekenig_announcements"),
    ),
    "max_lovekenig_announcements": (
        ("ВКонтакте", "vk_972b45c6f71c0f2a1fb9"),
        ("Телеграм", "tg_5060f37d74cf460135ee"),
    ),
}
# Public handles verified from owner posts / Telegram channel. Never derive a MAX
# vanity URL from the opaque provider-native browser target.
PUBLIC_HANDLES = {
    "max_lovekenig_announcements": ("max", "https://max.ru/channel_kenigevents"),
    "tg_5060f37d74cf460135ee": ("telegram", "https://t.me/kenigevents"),
}


def _public_url(alias, lookup):
    binding = lookup(alias)  # Active, owner-authorized destination registry.
    provider = binding["provider"]
    if alias in PUBLIC_HANDLES:
        expected, url = PUBLIC_HANDLES[alias]
        if provider != expected:
            raise DomainError("network_footer_target_mismatch")
        return url
    if provider == "vk" and re.fullmatch(r"-[1-9][0-9]*", str(binding["native_id"])):
        # The numeric club URL continues to work if a VK page's vanity name changes.
        return "https://vk.com/club" + str(-int(binding["native_id"]))
    raise DomainError("network_footer_target_mismatch")


def _identity(value):
    """Normalize public link identity, not the user's editorial text."""
    try:
        parts = urlsplit(value.strip())
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname.lower().removeprefix("www.")
        if host in {"vk.com", "vk.ru"}:
            host = "vk.com"
            # VK community /clubN and /publicN are equivalent navigation.
            path = re.sub(r"^/(?:public|club)([1-9][0-9]*)/?$", r"/club\1", parts.path)
        else:
            path = parts.path
        return host, path.rstrip("/").casefold()
    except ValueError:
        return None


def _tail_destinations(text, entities):
    """Recognize URL-bearing navigation near the end, irrespective of labels/spaces."""
    offset = max(text.rfind("\n\n") + 2, text.rfind("\n") + 1, 0)
    tail = text[offset:]
    found = set()
    for entity in entities:
        if entity["type"] == "text_link" and entity["offset"] >= utf16(text[:offset]):
            identity = _identity(entity["url"])
            if identity:
                found.add(identity)
    for match in re.finditer(r"https://[^\s<>]+", tail):
        identity = _identity(match.group().rstrip(".,;!?)"))
        if identity:
            found.add(identity)
    return found


def append_network_footer(source_alias, provider, content, lookup, *, has_media=False):
    """Return a new provider-ready semantic document, or the untouched input.

    Native forwards, edits, provider overrides and scope checks belong to the
    caller; this helper never mutates authored content or provider state.
    """
    rules = ROUTES.get(source_alias)
    if not rules:
        return content
    if provider != ("max" if source_alias == "max_lovekenig_announcements" else "telegram"):
        raise DomainError("network_footer_source_mismatch")
    if not content.get("text", "").strip() and not has_media:
        return content  # An empty text-only publication must still be rejected.
    compiled = copy.deepcopy(content)
    if compiled.get("format", "plain") not in ("plain", "telegram_entities", "max_entities"):
        raise DomainError("network_footer_content_unsupported")
    if compiled.get("format") == "max_entities" and provider != "max":
        raise DomainError("network_footer_content_unsupported")
    if compiled.get("format") == "telegram_entities" and provider != "telegram":
        raise DomainError("network_footer_content_unsupported")
    text = compiled["text"]
    entities = normalized_entities(text, compiled.get("entities", []))
    linked = _tail_destinations(text, entities)
    missing = []
    for caption, target_alias in rules:
        url = _public_url(target_alias, lookup)
        if _identity(url) not in linked:
            missing.append((caption, url))
    if not missing:
        return content
    gap = ("\n\n" if not text.endswith("\n") else "\n" if not text.endswith("\n\n") else "") if text else ""
    footer = "  ·  ".join(caption for caption, _ in missing)
    full = text + gap + footer
    limit = 1024 if provider == "telegram" and has_media else 4096 if provider == "telegram" else 32768
    if utf16(full) > limit:
        raise DomainError(
            "network_footer_limit",
            "The text and navigation footer exceed the provider limit; shorten the post or caption.",
        )
    start = utf16(text + gap)
    added = []
    for number, (caption, url) in enumerate(missing):
        if number:
            start += utf16("  ·  ")
        added.append({"type": "text_link", "offset": start, "length": utf16(caption), "url": url})
        start += utf16(caption)
    compiled.update(text=full, format="telegram_entities" if provider == "telegram" else "max_entities",
                    entities=normalized_entities(full, entities + added))
    return compiled
