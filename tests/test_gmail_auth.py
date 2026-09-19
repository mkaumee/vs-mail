"""Authorising Gmail as a web application.

The flow has one unguarded route in it, which is unavoidable — Google
redirects a browser there and a browser redirect carries no header — so the
tests are mostly about what stops that route being useful to anybody else.
"""
import json

import pytest
from fastapi.testclient import TestClient

from api import app_routes
from api.main import app
from vsmail.gmail import client as gmail

TOKEN = "test-token"

WEB_CLIENT = {
    "web": {
        "client_id": "id.apps.googleusercontent.com",
        "client_secret": "secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:8000/gmail/auth/callback"],
    }
}

DESKTOP_CLIENT = {
    "installed": {
        "client_id": "id.apps.googleusercontent.com",
        "client_secret": "secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    """No stray token from the developer's own machine, and no stale state."""
    monkeypatch.delenv(gmail.TOKEN_ENV, raising=False)
    monkeypatch.delenv(gmail.CREDENTIALS_ENV, raising=False)
    monkeypatch.delenv("VS_OAUTH_REDIRECT", raising=False)
    monkeypatch.setattr(gmail, "CREDENTIALS", tmp_path / "credentials.json")
    monkeypatch.setattr(gmail, "TOKEN", tmp_path / "token.json")
    app_routes._PENDING.clear()
    yield
    app_routes._PENDING.clear()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("VS_SERVICE_TOKEN", TOKEN)
    return TestClient(app)


@pytest.fixture
def auth():
    return {"X-VS-Token": TOKEN}


def write(config: dict) -> None:
    gmail.CREDENTIALS.write_text(json.dumps(config))


# -- the client file -----------------------------------------------------
def test_a_web_client_is_accepted():
    write(WEB_CLIENT)
    assert "web" in gmail.client_config()


def test_a_desktop_client_is_refused_by_name():
    """Downloading the wrong client type is easy; the error must say so.

    Left to the library this surfaces as a KeyError from somewhere inside
    google-auth, which tells nobody what to do about it.
    """
    write(DESKTOP_CLIENT)
    with pytest.raises(gmail.NotAuthorised) as raised:
        gmail.client_config()
    assert "Desktop app" in str(raised.value)
    assert "Web application" in str(raised.value)


def test_the_environment_can_hold_the_client(monkeypatch):
    """A deployment has no file to read: the download is gitignored, so it
    never reaches the image."""
    monkeypatch.setenv(gmail.CREDENTIALS_ENV, json.dumps(WEB_CLIENT))
    assert gmail.client_config() == WEB_CLIENT
    assert gmail.configured() is True


def test_the_environment_wins_over_the_file(monkeypatch):
    write(DESKTOP_CLIENT)
    monkeypatch.setenv(gmail.CREDENTIALS_ENV, json.dumps(WEB_CLIENT))
    assert "web" in gmail.client_config()


def test_the_wrong_client_type_is_caught_in_the_environment_too(monkeypatch):
    monkeypatch.setenv(gmail.CREDENTIALS_ENV, json.dumps(DESKTOP_CLIENT))
    with pytest.raises(gmail.NotAuthorised) as raised:
        gmail.client_config()
    assert "Desktop app" in str(raised.value)


def test_nothing_configured_is_reported_as_such():
    assert gmail.configured() is False


def test_a_missing_client_file_explains_the_setup():
    with pytest.raises(gmail.NotAuthorised) as raised:
        gmail.client_config()
    assert "console.cloud.google.com" in str(raised.value)


# -- where the token lives -----------------------------------------------
def test_the_environment_holds_the_token_when_it_is_set(monkeypatch):
    """Railway's filesystem does not survive a redeploy, so it can go in a
    variable instead — and then the file must not be consulted at all."""
    gmail.TOKEN.write_text(json.dumps({"refresh_token": "from-disk"}))
    monkeypatch.setenv(gmail.TOKEN_ENV, json.dumps({"refresh_token": "from-env"}))
    assert gmail.stored_token()["refresh_token"] == "from-env"


def test_the_file_is_used_when_the_environment_is_not_set():
    gmail.TOKEN.write_text(json.dumps({"refresh_token": "from-disk"}))
    assert gmail.stored_token()["refresh_token"] == "from-disk"


def test_no_token_anywhere_is_not_authorised():
    assert gmail.stored_token() is None
    assert gmail.authorised() is False


def test_storing_writes_nothing_when_the_environment_holds_the_token(monkeypatch):
    """Otherwise a stale file is left behind that nothing reads."""
    monkeypatch.setenv(gmail.TOKEN_ENV, json.dumps({"refresh_token": "from-env"}))

    class Creds:
        def to_json(self):
            return "{}"

    gmail.store(Creds())
    assert not gmail.TOKEN.exists()


def test_credentials_without_a_token_says_what_to_do():
    with pytest.raises(gmail.NotAuthorised) as raised:
        gmail.credentials()
    assert "Connect Gmail" in str(raised.value)


# -- the redirect URI ----------------------------------------------------
def test_the_redirect_defaults_to_localhost():
    assert gmail.redirect_uri() == gmail.DEFAULT_REDIRECT


def test_the_redirect_is_configuration_not_guesswork(monkeypatch):
    """Behind a proxy the request's own scheme and host are not reliable, and
    Google matches the registered URI exactly."""
    monkeypatch.setenv("VS_OAUTH_REDIRECT", "https://vs.example/gmail/auth/callback")
    assert gmail.redirect_uri() == "https://vs.example/gmail/auth/callback"


# -- starting consent ----------------------------------------------------
def test_starting_consent_needs_the_service_token(client):
    assert client.get("/gmail/auth/start").status_code == 401


def test_starting_consent_with_the_wrong_client_type_explains_itself(client, auth):
    write(DESKTOP_CLIENT)
    response = client.get("/gmail/auth/start", headers=auth)
    assert response.status_code == 400
    assert "Web application" in response.json()["detail"]


def test_starting_consent_returns_where_to_send_the_browser(client, auth, monkeypatch):
    monkeypatch.setattr(gmail, "authorization_url", lambda: ("https://accounts/x", "s1", "verifier-1"))
    body = client.get("/gmail/auth/start", headers=auth).json()
    assert body["authorization_url"] == "https://accounts/x"
    assert "s1" in app_routes._PENDING


# -- the callback --------------------------------------------------------
def test_the_callback_is_reachable_without_the_service_token(client):
    """It has to be: Google redirects a browser to it."""
    response = client.get("/gmail/auth/callback", follow_redirects=False)
    assert response.status_code != 401


def test_an_unknown_state_is_refused(client, monkeypatch):
    """The guard on the unguarded route. `state` can only be minted behind
    the service token, so a stranger has nothing to present."""
    called = []
    monkeypatch.setattr(gmail, "exchange", lambda *a: called.append(a))

    response = client.get(
        "/gmail/auth/callback?code=c&state=forged", follow_redirects=False
    )
    assert response.headers["location"] == "/?gmail=expired"
    assert called == []


def test_a_state_from_a_real_start_completes(client, auth, monkeypatch):
    monkeypatch.setattr(gmail, "authorization_url", lambda: ("https://accounts/x", "s1", "verifier-1"))
    client.get("/gmail/auth/start", headers=auth)

    exchanged = []
    monkeypatch.setattr(gmail, "exchange", lambda *a: exchanged.append(a))

    response = client.get(
        "/gmail/auth/callback?code=the-code&state=s1", follow_redirects=False
    )
    assert response.headers["location"] == "/?gmail=connected"
    # The PKCE verifier has to survive from the start route to here. It is
    # generated when the authorisation URL is built and the exchange happens
    # on a different Flow in a different request, so dropping it fails every
    # authorisation at the last step with `invalid_grant`.
    assert exchanged == [("the-code", "s1", "verifier-1")]


def test_the_authorisation_url_asks_for_what_a_refresh_token_needs(tmp_path):
    """Without `access_type=offline` and `prompt=consent` Google issues no
    refresh token, and the mailbox goes dead an hour later."""
    from urllib.parse import parse_qs, urlsplit

    write(WEB_CLIENT)
    url, state, verifier = gmail.authorization_url()
    query = parse_qs(urlsplit(url).query)

    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["scope"] == gmail.SCOPES
    assert query["redirect_uri"] == [gmail.DEFAULT_REDIRECT]
    assert query["state"] == [state]
    # PKCE is on by default, which is what makes the verifier load-bearing.
    assert query["code_challenge_method"] == ["S256"]
    assert verifier


def test_a_state_is_single_use(client, auth, monkeypatch):
    monkeypatch.setattr(gmail, "authorization_url", lambda: ("https://accounts/x", "s1", "verifier-1"))
    client.get("/gmail/auth/start", headers=auth)
    monkeypatch.setattr(gmail, "exchange", lambda *a: None)

    first = client.get("/gmail/auth/callback?code=c&state=s1", follow_redirects=False)
    second = client.get("/gmail/auth/callback?code=c&state=s1", follow_redirects=False)
    assert first.headers["location"] == "/?gmail=connected"
    assert second.headers["location"] == "/?gmail=expired"


def test_a_stale_state_is_refused(client, auth, monkeypatch):
    monkeypatch.setattr(gmail, "authorization_url", lambda: ("https://accounts/x", "s1", "verifier-1"))
    client.get("/gmail/auth/start", headers=auth)
    started, verifier = app_routes._PENDING["s1"]
    app_routes._PENDING["s1"] = (started - app_routes.STATE_TTL - 1, verifier)

    monkeypatch.setattr(gmail, "exchange", lambda *a: None)
    response = client.get("/gmail/auth/callback?code=c&state=s1", follow_redirects=False)
    assert response.headers["location"] == "/?gmail=expired"


def test_a_refusal_on_the_consent_screen_is_reported(client):
    response = client.get(
        "/gmail/auth/callback?error=access_denied", follow_redirects=False
    )
    assert response.headers["location"].startswith("/?gmail=denied")


def test_a_failed_exchange_does_not_leak_the_reason(client, auth, monkeypatch):
    """Whatever the library raised is for the log, not for a URL."""
    monkeypatch.setattr(gmail, "authorization_url", lambda: ("https://accounts/x", "s1", "verifier-1"))
    client.get("/gmail/auth/start", headers=auth)

    def boom(*args):
        raise RuntimeError("client_secret=hunter2 rejected")

    monkeypatch.setattr(gmail, "exchange", boom)
    response = client.get("/gmail/auth/callback?code=c&state=s1", follow_redirects=False)
    assert response.headers["location"] == "/?gmail=failed"
