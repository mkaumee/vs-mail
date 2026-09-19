"""Authorising this web app against Gmail.

VS-Mail is a web application, so the OAuth client is one too. That is not a
cosmetic difference. A "Desktop app" client authorises by opening a browser
on the machine running the code and catching the redirect on a loopback port
— which cannot work on Railway, where there is no browser and no localhost to
come back to. A web client redirects to a URL registered in advance, so
consent happens in the operator's own browser and lands back on this service
wherever it happens to be running.

Consequently there is no "log in from the terminal" path. A person clicks
Connect Gmail in the app, approves the scope, and the credential is stored.
Scripts use whatever that produced; they never prompt for anything.

One scope covers everything: `gmail.modify` permits inserting, reading,
sending and labelling, so it is one consent screen rather than four.

Neither the client secret nor the token is ever committed — both paths are
gitignored, and the token may live in an environment variable instead.
Imports of the Google libraries are deferred into the functions so that the
rest of the package, and the test suite, work without them installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

#: Inserting, reading, sending and labelling. `gmail.readonly` would not
#: permit most of those; `https://mail.google.com/` grants far more than is
#: needed, including permanent deletion of anything in the account.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

#: The OAuth client downloaded from the Google Cloud console, of type
#: "Web application".
CREDENTIALS = Path(os.environ.get("VS_GMAIL_CREDENTIALS", "credentials.json"))

#: Where the authorised token is written after consent.
TOKEN = Path(os.environ.get("VS_GMAIL_TOKEN", "token.json"))

#: The token as JSON, for a deployment whose filesystem does not survive a
#: redeploy. Set this and the file is not consulted at all.
TOKEN_ENV = "VS_GMAIL_TOKEN_JSON"

#: Where Google sends the browser back to. It must match a URI registered on
#: the OAuth client *exactly*, so it is configuration rather than something
#: derived from the incoming request — behind a proxy the request's own idea
#: of its scheme and host is not reliable.
DEFAULT_REDIRECT = "http://localhost:8000/gmail/auth/callback"


class NotAuthorised(RuntimeError):
    """No usable credential. Someone has to approve the consent screen."""


SETUP_HELP = f"""
Gmail needs a one-off setup that cannot be automated:

  1. Create a project at https://console.cloud.google.com and enable the
     Gmail API.
  2. Under Credentials, create an OAuth client ID of type "Web application".
  3. Add an authorised redirect URI for every place this app runs:
       {DEFAULT_REDIRECT}
       https://<your-railway-domain>/gmail/auth/callback
  4. Download the client and save it as {CREDENTIALS} in the repository root.
  5. On the OAuth consent screen, add the mailbox account as a Test user.
     The app is unverified, so only listed accounts may authorise it.

Then start the app and press Connect Gmail.
"""

WRONG_CLIENT_TYPE = f"""
{CREDENTIALS} is a "Desktop app" OAuth client, which this service cannot use.

A desktop client authorises by opening a browser locally and catching the
redirect on a loopback port. There is no browser on a deployed server, so
that flow has nowhere to run.

Create a new OAuth client of type "Web application" instead, add the
redirect URIs listed in the setup help, and replace {CREDENTIALS}.
"""


def redirect_uri() -> str:
    return os.environ.get("VS_OAUTH_REDIRECT", DEFAULT_REDIRECT)


def client_config() -> dict:
    """The OAuth client, checked for being the right kind of client.

    Downloading a Desktop client by mistake is an easy thing to do and the
    resulting failure is otherwise a KeyError deep inside a library.
    """
    if not CREDENTIALS.is_file():
        raise NotAuthorised(SETUP_HELP)
    config = json.loads(CREDENTIALS.read_text())
    if "web" not in config:
        raise NotAuthorised(WRONG_CLIENT_TYPE if "installed" in config else SETUP_HELP)
    return config


def _flow(state: str | None = None):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        client_config(), scopes=SCOPES, state=state, redirect_uri=redirect_uri()
    )


def authorization_url() -> tuple[str, str, str]:
    """Where to send the operator's browser, plus what the callback will need.

    `access_type=offline` with `prompt=consent` is what makes Google issue a
    refresh token. Without both, a second authorisation returns only an access
    token and the mailbox goes dead an hour later.

    The third value is the PKCE code verifier. The library generates one here
    and puts its hash in the URL, so the exchange has to present the same
    verifier — and the exchange happens in a different request, on a different
    `Flow` object, which would otherwise have none. Losing it means every
    authorisation fails at the last step with `invalid_grant`.
    """
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    return url, state, flow.code_verifier


def exchange(code: str, state: str, code_verifier: str | None = None) -> None:
    """Turn the code Google handed back into a stored credential."""
    flow = _flow(state=state)
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    granted = set(flow.credentials.scopes or [])
    if not granted.issuperset(SCOPES):
        # The consent screen lets a person untick permissions. Saying so now
        # beats a confusing 403 at the first insert.
        raise NotAuthorised(
            "Gmail access was not granted. Approve the 'Read, compose, send "
            "and permanently delete' permission and try again."
        )
    store(flow.credentials)


def store(creds) -> None:
    """Persist a credential, unless the environment is holding it.

    When the token comes from the environment the file is not consulted, so
    writing one would only leave a stale copy behind to confuse the next
    person who looks.
    """
    if os.environ.get(TOKEN_ENV):
        return
    TOKEN.write_text(creds.to_json())


def stored_token() -> dict | None:
    """The authorised token, from the environment or from disk.

    The environment wins. Railway's filesystem does not survive a redeploy, so
    a deployment that must stay connected puts the token in a variable and
    the file never enters the picture.
    """
    raw = os.environ.get(TOKEN_ENV)
    if raw:
        return json.loads(raw)
    if TOKEN.is_file():
        return json.loads(TOKEN.read_text())
    return None


def authorised() -> bool:
    return stored_token() is not None


def credentials():
    """A live credential, refreshed if the access token has expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    info = stored_token()
    if info is None:
        raise NotAuthorised(
            "Gmail is not connected. Open the app and press Connect Gmail."
        )

    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store(creds)
        return creds
    raise NotAuthorised(
        "The stored Gmail authorisation cannot be refreshed. Press Connect "
        "Gmail again to issue a new one."
    )


def service():
    """A Gmail API handle for the authorised mailbox."""
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)


def service_or_exit():
    """`service()`, but a script exits with the explanation instead of a
    traceback. The failure here is always a setup step, never a bug."""
    try:
        return service()
    except NotAuthorised as exc:
        raise SystemExit(str(exc))


def address(svc) -> str:
    """Which mailbox we are talking to.

    Worth printing before anything writes to it: seeding the wrong account is
    tedious to undo.
    """
    return svc.users().getProfile(userId="me").execute().get("emailAddress", "unknown")
