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

#: The same client as JSON. A deployment has no file to read: the download is
#: gitignored, so it is never in the image. Set this and the file is not
#: consulted at all.
CREDENTIALS_ENV = "VS_GMAIL_CREDENTIALS_JSON"

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
  4. Download the client. Locally, save it as {CREDENTIALS} in the repository
     root; deployed, put its contents in {CREDENTIALS_ENV} instead, since the
     download is gitignored and never reaches the image.
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
redirect URIs listed in the setup help, and replace it.
"""


def redirect_uri() -> str:
    return os.environ.get("VS_OAUTH_REDIRECT", DEFAULT_REDIRECT)


def _parse(raw: str, where: str) -> dict:
    """JSON, or an explanation of the paste that probably went wrong.

    Both of these values are pasted by hand into a deployment's environment,
    and the two ways that goes wrong are specific enough to name: a Raw-Editor
    paste leaves the `KEY=` on the front, and a truncated copy stops mid-brace.
    Left to `json.loads` the operator gets a 500 and no idea which.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        hint = ""
        stripped = raw.strip()
        if "=" in stripped.split("{", 1)[0]:
            hint = (
                " It looks like the variable name was pasted along with the "
                "value — the value should begin with '{'."
            )
        elif stripped.startswith("{") and not stripped.endswith("}"):
            hint = " It looks truncated — the value should end with '}'."
        raise NotAuthorised(
            f"{where} is set but is not valid JSON ({exc.msg}).{hint}"
        ) from exc


def client_config() -> dict:
    """The OAuth client, from the environment or from disk.

    Checked for being the right kind of client, because downloading a Desktop
    one by mistake is easy and the resulting failure is otherwise a KeyError
    deep inside a library.
    """
    raw = os.environ.get(CREDENTIALS_ENV)
    if raw:
        config = _parse(raw, CREDENTIALS_ENV)
    elif CREDENTIALS.is_file():
        config = _parse(CREDENTIALS.read_text(), str(CREDENTIALS))
    else:
        raise NotAuthorised(SETUP_HELP)

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


def forget() -> dict:
    """Disconnect the mailbox, at Google's end as well as ours.

    Deleting our copy alone is not a disconnect: Google still trusts the
    grant, so reconnecting skips the consent screen entirely and anyone who
    kept a copy of the token can still use it. Revoking kills the refresh
    token where it actually lives.

    ⚠️ When the token came from VS_GMAIL_TOKEN_JSON we cannot remove it — a
    process cannot unset its deployment's environment variable. The revoke
    still works, so what is left behind is a dead token in a variable, and
    saying so by name beats reporting a clean disconnect that was not.
    """
    import httpx

    result = {
        "revoked": False,
        "file_removed": False,
        "still_in_environment": bool(os.environ.get(TOKEN_ENV)),
    }

    try:
        info = stored_token()
    except NotAuthorised:
        info = None
    if info is None:
        return result

    token = info.get("refresh_token") or info.get("token")
    if token:
        try:
            response = httpx.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
            # Google answers 200 for a revoked token and 400 for one that was
            # already invalid. Both mean it cannot be used, which is what was
            # asked for.
            result["revoked"] = response.status_code in (200, 400)
        except Exception:
            # Offline, or Google refused. The local copy still goes, and the
            # caller is told the grant may still stand.
            result["revoked"] = False

    if TOKEN.is_file():
        TOKEN.unlink()
        result["file_removed"] = True
    return result


def stored_token() -> dict | None:
    """The authorised token, from the environment or from disk.

    The environment wins. Railway's filesystem does not survive a redeploy, so
    a deployment that must stay connected puts the token in a variable and
    the file never enters the picture.
    """
    raw = os.environ.get(TOKEN_ENV)
    if raw:
        return _parse(raw, TOKEN_ENV)
    if TOKEN.is_file():
        return _parse(TOKEN.read_text(), str(TOKEN))
    return None


def configured() -> bool:
    """Whether there is a usable OAuth client to authorise against.

    Not the same as being authorised: a deployment can be configured and
    still waiting for someone to approve the consent screen.

    This has to actually parse the client, not merely find a non-empty
    variable. Reporting a mangled paste as configured sends the operator
    looking everywhere except at the value they pasted.
    """
    try:
        client_config()
    except NotAuthorised:
        return False
    return True


def credentials_source() -> str | None:
    """Where the OAuth client is being read from, for diagnostics."""
    if os.environ.get(CREDENTIALS_ENV):
        return "environment"
    return "file" if CREDENTIALS.is_file() else None


def token_source() -> str | None:
    """Where the stored token is being read from, for diagnostics."""
    if os.environ.get(TOKEN_ENV):
        return "environment"
    return "file" if TOKEN.is_file() else None


def authorised() -> bool:
    try:
        return stored_token() is not None
    except NotAuthorised:
        return False


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
        try:
            creds.refresh(Request())
        except Exception as exc:
            # Almost always `invalid_grant`, and almost always the same cause:
            # `gmail.modify` is a restricted scope, so a consent screen left in
            # Testing issues refresh tokens that expire after seven days.
            # Publishing is not the fix — a restricted scope pulls in Google's
            # full verification plus a CASA assessment, and a *.up.railway.app
            # domain cannot be verified as ours. Re-consenting weekly is the
            # operating condition, so this needs to say so rather than surface
            # a library error nobody can act on.
            raise NotAuthorised(
                "The Gmail authorisation has expired or been revoked. Press "
                "Connect Gmail again. Consent screens in Testing issue tokens "
                f"that last seven days, so this is expected. ({exc})"
            ) from exc
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
