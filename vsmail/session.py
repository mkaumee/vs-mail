"""Who is signed in, carried in a signed cookie.

A cookie rather than a server-side session because Railway's filesystem does
not survive a redeploy: anything kept there is lost on every push, and the
whole point of signing in is not having to do it again.

Signed, not encrypted. Nothing in the payload is secret — an email address the
person just typed into Google's own consent screen — and a reader who can see
the cookie is the person it belongs to. What matters is that it cannot be
*edited*, because the email in it is the identity every route downstream
believes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

#: Seven days. Long enough not to be a nuisance, short enough that a laptop
#: left behind stops working on its own.
LIFETIME = 7 * 24 * 60 * 60

COOKIE = "vs_session"

SECRET_ENV = "VS_SESSION_SECRET"


class BadSession(ValueError):
    """The cookie is missing, altered, or past its expiry."""


def secret() -> bytes:
    """The signing key.

    Falls back to VS_SERVICE_TOKEN so a deployment needs no new variable: it
    is already a long random string that only the server knows, which is the
    whole requirement. Setting VS_SESSION_SECRET separately is still better —
    rotating the service token then does not sign everybody out.
    """
    raw = os.environ.get(SECRET_ENV) or os.environ.get("VS_SERVICE_TOKEN", "")
    if not raw:
        # Same posture as api/auth.py: refuse rather than sign with a default
        # that every deployment of this code would share.
        raise BadSession("no signing secret; set VS_SESSION_SECRET")
    return raw.encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign(payload: dict, lifetime: int = LIFETIME) -> str:
    """A cookie value carrying `payload` and an expiry."""
    body = {**payload, "exp": int(time.time()) + lifetime}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    mac = hmac.new(secret(), raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(mac)}"


def verify(cookie: str) -> dict:
    """The payload, or `BadSession`.

    The expiry is checked *after* the signature, and separately: a valid
    signature over a stale payload is still stale. Leaving that to the
    cookie's own Max-Age would trust the browser to enforce it.
    """
    if not cookie or "." not in cookie:
        raise BadSession("no session")
    encoded, _, signature = cookie.partition(".")
    try:
        raw = _unb64(encoded)
        given = _unb64(signature)
    except Exception as exc:
        raise BadSession("malformed session") from exc

    expected = hmac.new(secret(), raw, hashlib.sha256).digest()
    # Constant-time, so a forged signature cannot be found one byte at a time.
    if not hmac.compare_digest(expected, given):
        raise BadSession("session signature does not match")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadSession("session payload is not readable") from exc

    if payload.get("exp", 0) < time.time():
        raise BadSession("session has expired")
    return payload
