"""Proving the caller may be here.

Two ways in, because two kinds of caller exist and they cannot use the same
one. A browser signs in with Google and carries a session cookie. Scripts,
`RemoteProvider` and curl carry the shared secret in a header; there is no
browser to sign in with and nowhere to put a cookie.

An unauthenticated model endpoint on a public URL gets found and drained, and
the bill is real. So if VS_SERVICE_TOKEN is unset the service refuses
authenticated routes outright rather than running open to the world: failing
closed is the only safe default for a deployment that spends money.
"""
from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request, status

from vsmail.session import COOKIE, BadSession, verify

TOKEN_HEADER = "X-VS-Token"


def configured_token() -> str:
    return os.environ.get("VS_SERVICE_TOKEN", "")


def session_of(request: Request) -> dict | None:
    """The signed-in person, if there is one. Never raises."""
    try:
        return verify(request.cookies.get(COOKIE, ""))
    except BadSession:
        return None


async def require_access(request: Request) -> None:
    """A valid session cookie, or the shared secret. Either will do."""
    expected = configured_token()
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "VS_SERVICE_TOKEN is not configured; authenticated routes are "
                "disabled rather than served without a guard."
            ),
        )

    if session_of(request) is not None:
        return

    # Constant-time, so a wrong token cannot be found one character at a time.
    given = request.headers.get(TOKEN_HEADER, "")
    if secrets.compare_digest(given, expected):
        return

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="sign in, or present a valid service token",
    )


#: The old name, kept because every router hangs off it.
require_token = require_access
