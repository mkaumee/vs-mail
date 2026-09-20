"""Signing in and out.

Separate from the Gmail routes on purpose. Signing in says who is using this;
connecting a mailbox says which mailbox it works on. Doing one should never
imply the other, and the consent screens ask for different things — this one
asks only for a name and an email address.

The first three routes are unguarded by necessity: you cannot present a
session before you have one, and the callback is a browser redirect with
nowhere to put a header.
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from api.auth import session_of
from vsmail import identity, session

auth_router = APIRouter(prefix="/auth")

#: Authorisations begun and not yet come back, keyed by the `state` Google
#: will hand us, holding when it started and the PKCE verifier the exchange
#: will need. Same shape as the Gmail flow's, for the same reasons.
_PENDING: dict[str, tuple[float, str | None]] = {}

STATE_TTL = 600.0


def _drop_stale(now: float) -> None:
    for state, (started, _) in list(_PENDING.items()):
        if now - started > STATE_TTL:
            _PENDING.pop(state, None)


def _secure(request: Request) -> bool:
    """Whether to mark the cookie Secure. Off for localhost, or the browser
    drops it and signing in appears to do nothing."""
    return request.url.scheme == "https"


@auth_router.get("/status")
async def auth_status(request: Request) -> dict:
    """Enough to diagnose a sign-in that will not start.

    `redirect_uri` is here because a mismatch with what is registered in the
    Google console is the failure this project has hit more than any other,
    and it is otherwise invisible until the browser is already at Google.
    """
    return {
        "configured": identity.configured(),
        "redirect_uri": identity.redirect_uri(),
        "signed_in": session_of(request) is not None,
        "token_accepted": bool(os.environ.get("VS_SERVICE_TOKEN")),
    }


@auth_router.get("/login")
async def login() -> dict:
    """Where to send the browser."""
    from vsmail.gmail.client import NotAuthorised

    try:
        url, state, verifier = identity.authorization_url()
    except NotAuthorised as exc:
        raise HTTPException(400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(400, detail=f"sign-in could not be set up: {exc}")

    now = time.time()
    # Prune first, then store: popping before pruning is how an authorisation
    # begun hours ago was still completing, and that bug is not worth having
    # twice.
    _drop_stale(now)
    _PENDING[state] = (now, verifier)
    return {"authorization_url": url}


@auth_router.get("/callback", include_in_schema=False)
async def callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Where Google returns the person after they approve.

    Unauthenticated by necessity — a browser redirect carries no header — so
    `state` is the guard: it was minted by /auth/login, is single-use, and is
    dropped once it is older than STATE_TTL.
    """
    from vsmail.gmail.client import NotAuthorised

    if error:
        return RedirectResponse(f"/?signin=denied&detail={error}")

    _drop_stale(time.time())
    pending = _PENDING.pop(state, None)
    if pending is None:
        return RedirectResponse("/?signin=expired")

    try:
        who = identity.exchange(code, state, pending[1])
    except NotAuthorised as exc:
        return RedirectResponse(f"/?signin=denied&detail={exc}")
    except Exception:
        return RedirectResponse("/?signin=failed")

    response = RedirectResponse("/?signin=ok")
    response.set_cookie(
        session.COOKIE,
        session.sign(who.as_dict()),
        max_age=session.LIFETIME,
        httponly=True,
        samesite="lax",
        secure=_secure(request),
        path="/",
    )
    return response


@auth_router.get("/me")
async def me(request: Request) -> dict:
    """Who is signed in. 401 rather than null, so the page can act on it."""
    who = session_of(request)
    if who is None:
        raise HTTPException(401, detail="not signed in")
    return {
        "email": who.get("email", ""),
        "name": who.get("name", ""),
        "picture": who.get("picture", ""),
    }


@auth_router.post("/logout")
async def logout(response: Response) -> dict:
    """Forget the session. The service token, if one is held, is the page's
    to drop — it was never sent here."""
    response.delete_cookie(session.COOKIE, path="/")
    return {"signed_out": True}
