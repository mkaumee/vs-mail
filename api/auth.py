"""Shared-secret guard.

An unauthenticated model endpoint on a public URL gets found and drained,
and the bill is real. Every route except /health requires the token.

If VS_SERVICE_TOKEN is unset the service refuses authenticated routes
outright rather than running open to the world: failing closed is the only
safe default for a deployment that spends money.
"""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status

TOKEN_HEADER = "X-VS-Token"


def configured_token() -> str:
    return os.environ.get("VS_SERVICE_TOKEN", "")


async def require_token(x_vs_token: str = Header(default="")) -> None:
    expected = configured_token()
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "VS_SERVICE_TOKEN is not configured; authenticated routes are "
                "disabled rather than served without a guard."
            ),
        )
    # Constant-time, so a wrong token cannot be found one character at a time.
    if not secrets.compare_digest(x_vs_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")
