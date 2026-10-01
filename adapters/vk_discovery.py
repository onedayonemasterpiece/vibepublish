"""Read-only exact VK community discovery on the existing worker connection."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from social_operations.domain import DomainError


def parse_destination(command):
    """Return a provider selector without enumerating account resources."""
    url = command.get("url")
    provider_id = command.get("provider_id")
    if bool(url) == bool(provider_id):
        raise DomainError("vk_destination_reference_invalid")
    if provider_id:
        if not isinstance(provider_id, str) or not re.fullmatch(r"-?[1-9][0-9]{0,18}", provider_id):
            raise DomainError("vk_destination_id_invalid")
        return str(abs(int(provider_id)))
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc.lower() not in {"vk.com", "www.vk.com", "vk.ru", "www.vk.ru"}
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in {None, 443} or parsed.query or parsed.fragment):
        raise DomainError("vk_destination_url_invalid")
    path = parsed.path.rstrip("/")
    match = re.fullmatch(r"/([A-Za-z0-9_.-]{2,128})", path)
    if not match:
        raise DomainError("vk_destination_url_invalid")
    return match.group(1)


async def resolve(adapter, command):
    """Resolve one explicit community and prove current publishing authority."""
    selector = parse_destination(command)
    if adapter.account_type not in {"vk_user", "vk_group"}:
        raise DomainError("vk_discovery_connection_unsupported")
    response = await adapter._call(
        "groups.getById", role="reader", group_ids=selector,
        fields="is_admin,admin_level,is_closed,screen_name,name",
    )
    groups = response.get("groups") if isinstance(response, dict) else response
    if not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], dict):
        raise DomainError("vk_group_identity_mismatch")
    group = groups[0]
    ident = group.get("id")
    if type(ident) is not int or ident <= 0:
        raise DomainError("vk_group_identity_mismatch")
    if selector.isdecimal() and ident != int(selector):
        raise DomainError("vk_group_identity_mismatch")
    if adapter.account_type == "vk_user":
        if group.get("is_admin") != 1 or type(group.get("admin_level")) is not int or group["admin_level"] < 2:
            raise DomainError("provider_access_denied")
    elif getattr(adapter.transport, "account_type", None) != "vk_group":
        raise DomainError("vk_account_type_mismatch")
    required = {
        "publish": ("editor", "wall.post"),
        "edit": ("editor", "wall.edit"),
        "reschedule": ("editor", "wall.edit"),
        "cancel": ("editor", "wall.delete"),
        "delete": ("editor", "wall.delete"),
        "forward": ("editor", "wall.repost"),
    }
    rights = []
    for right, (role, method) in required.items():
        if adapter.transport.permits(role, method, group_id=ident, scheduled=False):
            rights.append(right)
    if "publish" not in rights:
        raise DomainError("provider_access_denied")
    handle = group.get("screen_name") or ""
    label = group.get("name") or handle or f"VK community {ident}"
    if not isinstance(handle, str) or len(handle) > 128 or not isinstance(label, str) or not 1 <= len(label) <= 300:
        raise DomainError("vk_group_identity_mismatch")
    return {
        "native_id": f"-{ident}",
        "handle": handle,
        "label": label,
        "rights": rights,
    }
