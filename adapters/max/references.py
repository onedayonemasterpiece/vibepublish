"""Literal native MAX post references, bound to a separately verified target."""
from __future__ import annotations

import re

_RESERVED = frozenset({
    'auth', 'login', 'join', 'invite', 'token', 'session', 'oauth', 'oauth2',
    'authorize', 'callback', 'signin', 'signup', 'password', 'reset', 'code',
    'qr', 'sso', 'api', 'c', 'logout', 'authenticate', 'share', 'download',
    'privacy', 'terms',
})
_SLUG = r'[A-Za-z0-9_-]{1,128}'


def native_reference_id(value, target, *, public_url=None):
    """Return the opaque copied slug, never infer a handle-to-native mapping.

    public_url must come from a verified current target binding, not from value.
    Literal full matches exclude credentials, ports, encoded separators, query,
    fragment, whitespace and alternate hosts. The caller retains the copied URL.
    """
    if (not isinstance(value, str) or not isinstance(target, str)
            or not re.fullmatch(r'-[1-9][0-9]{0,19}', target)):
        return None
    native = re.fullmatch(r'https://max\.ru/c/' + re.escape(target) + '/(' + _SLUG + ')', value)
    if native:
        return native[1]
    if not isinstance(public_url, str):
        return None
    handle = re.fullmatch(r'https://max\.ru/([A-Za-z][A-Za-z0-9_]{2,127})', public_url)
    if not handle or handle[1].lower() in _RESERVED:
        return None
    post = re.fullmatch(re.escape(public_url) + '/(' + _SLUG + ')', value)
    return post[1] if post else None
