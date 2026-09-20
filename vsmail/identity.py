"""Signing in to the app, which is not the same as connecting a mailbox.

Two different questions. This one answers *who is using this*; the Gmail flow
in `vsmail/gmail/client.py` answers *which mailbox it works on*. Keeping them
apart means you can sign in with no mailbox attached, and that the mailbox
belongs to the deployment rather than to whoever happens to be looking at it.

Same OAuth client, so there is nothing further to configure — only a second
redirect URI to register. The scopes are the short ones: signing in never asks
for access to anybody's mail, so the consent screen says "see your name and
email address" and nothing more.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from vsmail.gmail.client import NotAuthorised, client_config

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

DEFAULT_REDIRECT = "http://localhost:8000/auth/callback"

#: Who may sign in. Empty means anyone with a Google account, which is the
#: deliberate default here — and the one variable that locks it down later
#: without a code change.
ALLOWED_ENV = "VS_ALLOWED_USERS"


@dataclass(frozen=True)
class Identity:
    """A person Google has vouched for."""

    email: str
    name: str = ""
    picture: str = ""

    def as_dict(self) -> dict:
        return {"email": self.email, "name": self.name, "picture": self.picture}


def redirect_uri() -> str:
    """Where Google sends the browser back.

    Configuration rather than something derived from the request: behind a
    proxy the request's own idea of its scheme and host is not reliable, and
    Google matches the registered URI exactly.
    """
    return os.environ.get("VS_AUTH_REDIRECT", DEFAULT_REDIRECT)


def allowed(email: str) -> bool:
    """Whether this person may in. Empty allowlist means everybody."""
    listed = [e.strip().lower() for e in os.environ.get(ALLOWED_ENV, "").split(",")]
    listed = [e for e in listed if e]
    return not listed or email.strip().lower() in listed


def _flow(state: str | None = None):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        client_config(), scopes=SCOPES, state=state, redirect_uri=redirect_uri()
    )


def authorization_url() -> tuple[str, str, str]:
    """Where to send the browser, plus what the callback will need.

    No `access_type=offline`: there is nothing to do later on this person's
    behalf, so there is no reason to hold a refresh token for them. The ID
    token comes back once, is read once, and the session cookie carries it
    from there.

    The third value is the PKCE verifier, which the exchange happens in a
    different request and would otherwise not have — the same trap as the
    Gmail flow, where losing it failed every authorisation with
    `invalid_grant`.
    """
    flow = _flow()
    url, state = flow.authorization_url(prompt="select_account")
    return url, state, flow.code_verifier


def exchange(code: str, state: str, code_verifier: str | None = None) -> Identity:
    """Turn the code Google handed back into a verified identity."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    flow = _flow(state=state)
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)

    raw = getattr(flow.credentials, "id_token", None)
    if not raw:
        raise NotAuthorised("Google returned no identity token.")

    # Audience-checked against our own client, so a token minted for some
    # other application cannot be replayed here.
    audience = client_config()["web"]["client_id"]
    claims = google_id_token.verify_oauth2_token(
        raw, google_requests.Request(), audience
    )

    email = claims.get("email", "")
    if not email:
        raise NotAuthorised("Google did not return an email address.")
    if not claims.get("email_verified", False):
        # An unverified address is not an identity — anyone can claim one.
        raise NotAuthorised(f"{email} is not a verified Google address.")
    if not allowed(email):
        raise NotAuthorised(
            f"{email} is signed in to Google but is not on this deployment's "
            f"list of permitted users."
        )
    return Identity(
        email=email,
        name=claims.get("name", ""),
        picture=claims.get("picture", ""),
    )


def configured() -> bool:
    """Whether there is an OAuth client to sign in against."""
    try:
        client_config()
    except NotAuthorised:
        return False
    return True
