"""Read-only exact Telegram destination discovery on the existing worker session."""
from __future__ import annotations

import re
from types import SimpleNamespace
from urllib.parse import urlsplit

from social_operations.domain import DomainError
from .telegram import peer_key


def parse_destination_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc not in {"t.me", "telegram.me"}
            or parsed.fragment):
        raise DomainError("telegram_destination_url_invalid")
    path = parsed.path.rstrip("/")
    invite = re.fullmatch(r"/(?:\+|joinchat/)([A-Za-z0-9_-]{8,128})", path)
    if invite:
        return "invite", invite.group(1)
    internal = re.fullmatch(r"/c/([1-9][0-9]*)(?:/[1-9][0-9]*){0,2}", path)
    if internal:
        return "peer", str(-1_000_000_000_000 - int(internal.group(1)))
    public = re.fullmatch(r"/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})(?:/[1-9][0-9]*){0,2}", path)
    if public and public.group(1).lower() not in {"joinchat", "addstickers", "addemoji", "share", "login", "proxy"}:
        return "peer", public.group(1)
    raise DomainError("telegram_destination_url_invalid")


async def basic_publish_rights(adapter, request, entity, me):
    # Ordinary basic-group posts stay immediate-only unless trusted core proves
    # this exact binding has the owner-granted basic_group_schedule right.
    schedule_allowed = (
        request.scheduled_at is None
        or bool(getattr(request, "basic_group_schedule_authorized", False))
    )
    if not (type(entity).__name__ == "Chat"
            and not getattr(entity, "deactivated", False)
            and getattr(entity, "migrated_to", None) is None
            and adapter.account_type == "mtproto_user"
            and request.action == "publish" and request.surface == "post"
            and request.existing is None
            and schedule_allowed
            and request.source is None):
        raise DomainError("telegram_group_mutations_needs_review", next_action="contact_owner")
    permissions = await adapter.client.get_permissions(entity, me)
    if (permissions is None or getattr(permissions, "is_banned", False)
            or getattr(permissions, "has_left", False)):
        raise DomainError("provider_access_denied")
    if getattr(permissions, "is_creator", False) or getattr(permissions, "is_admin", False):
        return
    banned = getattr(entity, "default_banned_rights", None)
    if (not getattr(permissions, "has_default_permissions", False)
            or getattr(banned, "send_messages", False)
            or getattr(banned, "send_plain", False)):
        raise DomainError("provider_access_denied")
    for asset in getattr(request, "assets", ()):
        restriction = "send_docs" if asset.role == "document" else "send_photos"
        if getattr(banned, "send_media", False) or getattr(banned, restriction, False):
            raise DomainError("provider_access_denied")


async def resolve(adapter, url):
    kind, selector = parse_destination_url(url)
    if adapter.account_type != "mtproto_user":
        raise DomainError("telegram_discovery_requires_user_connection")
    if kind == "invite":
        response = await adapter._call("check_invite", hash=selector)
        # Preview/peek is NOT membership. Never import an invite or join a chat.
        if type(response).__name__ != "ChatInviteAlready":
            raise DomainError("telegram_destination_membership_required", next_action="contact_owner")
        entity = response.chat
    else:
        entity = await adapter._entity(selector)
    target = peer_key(entity)
    if not target.startswith("-") or type(entity).__name__ in {"ChatForbidden", "ChannelForbidden"}:
        raise DomainError("telegram_destination_not_group_or_channel")
    if getattr(entity, "left", False) or getattr(entity, "kicked", False):
        raise DomainError("provider_access_denied")
    cache = getattr(adapter, "_entity_cache", None)
    if cache is not None:
        cache[target] = entity
    request = SimpleNamespace(connection_id=adapter.connection_id,
        account_type=adapter.account_type, native_target=target, action="publish",
        surface="post", existing=None, scheduled_at=None, source=None, assets=())
    observed = await adapter._rights(request)
    if peer_key(observed) != target:
        raise DomainError("telegram_peer_mismatch")
    rights = await lifecycle_rights(adapter, target)
    return {"native_id": target, "label": str(getattr(entity, "title", "Telegram group"))[:200],
            "handle": str(getattr(entity, "username", "") or ""), "rights": rights}


async def lifecycle_rights(adapter, target):
    """Read-only provider preflight for lifecycle operations on this exact peer."""
    rights = ["publish"]
    probes = (
        ("edit", SimpleNamespace(namespace="published"), None),
        ("reschedule", SimpleNamespace(namespace="scheduled"), "2030-01-01T00:00:00+00:00"),
        ("cancel", SimpleNamespace(namespace="scheduled"), "2030-01-01T00:00:00+00:00"),
        ("delete", SimpleNamespace(namespace="published"), None),
        ("forward", None, None),
    )
    for action, existing, scheduled_at in probes:
        request = SimpleNamespace(
            connection_id=adapter.connection_id,
            account_type=adapter.account_type,
            native_target=target,
            action=action,
            surface="post",
            existing=existing,
            scheduled_at=scheduled_at,
            source=None,
            assets=(),
        )
        try:
            observed = await adapter._rights(request)
        except DomainError:
            continue
        if peer_key(observed) != target:
            raise DomainError("telegram_peer_mismatch")
        rights.append(action)
    return rights
