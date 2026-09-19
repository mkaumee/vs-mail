"""Authenticating against Gmail.

One scope covers everything this needs: `gmail.modify` permits inserting
messages, reading them, sending and writing labels, so there is a single
consent screen rather than several.

Neither credential file ever enters the repository — both are gitignored,
and the token is written only after a person has approved the consent screen
themselves. Imports are deferred into the functions so that the rest of the
package, and the test suite, work without the Google libraries installed.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Inserting, reading, sending and labelling. `gmail.readonly` would not
#: permit most of those; `https://mail.google.com/` grants far more than is
#: needed, including permanent deletion of anything in the account.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

#: Downloaded from the Google Cloud console as an OAuth client of type
#: "Desktop app".
CREDENTIALS = Path(os.environ.get("VS_GMAIL_CREDENTIALS", "credentials.json"))

#: Written after the first consent, refreshed silently after that.
TOKEN = Path(os.environ.get("VS_GMAIL_TOKEN", "token.json"))

SETUP_HELP = f"""
{CREDENTIALS} was not found. Gmail needs a one-off setup that cannot be
automated:

  1. Create a project at https://console.cloud.google.com and enable the
     Gmail API.
  2. Under Credentials, create an OAuth client ID of type "Desktop app".
  3. Download it and save it as {CREDENTIALS} in the repository root.
  4. On the OAuth consent screen, add the mailbox account as a Test user.
     The app is unverified, so only listed accounts may authorise it.

Then run this again; a browser opens once to approve access.
"""


def credentials(interactive: bool = True):
    """Load stored credentials, refreshing or requesting consent as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN.is_file():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not interactive:
            raise RuntimeError(f"no usable {TOKEN}; run a command interactively once")
        if not CREDENTIALS.is_file():
            raise SystemExit(SETUP_HELP)
        creds = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS), SCOPES
        ).run_local_server(port=0)

    TOKEN.write_text(creds.to_json())
    return creds


def service(interactive: bool = True):
    """A Gmail API handle for the authorised mailbox."""
    from googleapiclient.discovery import build

    return build(
        "gmail", "v1", credentials=credentials(interactive), cache_discovery=False
    )


def address(svc) -> str:
    """Which mailbox we are talking to.

    Worth printing before anything writes to it: seeding the wrong account is
    tedious to undo.
    """
    return svc.users().getProfile(userId="me").execute().get("emailAddress", "unknown")
