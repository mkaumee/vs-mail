"""Signing in, staying in, and getting out.

The Google consent screen cannot be driven from a test, so the exchange is
stubbed and everything either side of it is real: the state guard, the cookie,
the two ways of satisfying the gate, and the sign-out.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from vsmail import session
from vsmail.identity import Identity

TOKEN = "test-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("VS_SERVICE_TOKEN", TOKEN)
    monkeypatch.delenv(session.SECRET_ENV, raising=False)
    return TestClient(app)


@pytest.fixture
def signed_in(client, monkeypatch):
    """A browser that has actually been through the callback.

    Setting the cookie on the jar by hand looks equivalent and is not: it
    lands without a domain, so the deletion a sign-out sends never matches it
    and logout appears broken when it is not. Going through the route also
    exercises the cookie attributes for real.
    """
    import time

    from api import auth_routes

    monkeypatch.setattr(
        auth_routes.identity,
        "exchange",
        lambda code, state, verifier: Identity(email="me@example.com", name="Me"),
    )
    auth_routes._PENDING["fixture"] = (time.time(), "verifier")
    client.get("/auth/callback?code=good&state=fixture", follow_redirects=False)
    return client


# -- the two ways in -----------------------------------------------------
def test_a_session_alone_opens_the_inbox(signed_in):
    """No token header at all. This is what a browser will have."""
    assert signed_in.get("/inbox").status_code == 200


def test_the_token_alone_still_works(client):
    """Scripts and RemoteProvider have no browser to sign in with."""
    assert client.get("/inbox", headers={"X-VS-Token": TOKEN}).status_code == 200


def test_neither_is_refused(client):
    assert client.get("/inbox").status_code == 401


def test_a_forged_session_is_refused(client):
    client.cookies.set(session.COOKIE, "not.asignature", domain="testserver")
    assert client.get("/inbox").status_code == 401


def test_an_expired_session_is_refused(client):
    client.cookies.set(
        session.COOKIE,
        session.sign({"email": "me@example.com"}, lifetime=-1),
        domain="testserver",
    )
    assert client.get("/inbox").status_code == 401


# -- who am I ------------------------------------------------------------
def test_me_is_401_when_signed_out(client):
    assert client.get("/auth/me").status_code == 401


def test_me_names_the_person(signed_in):
    assert signed_in.get("/auth/me").json()["email"] == "me@example.com"


def test_logout_clears_the_session(signed_in):
    assert signed_in.get("/auth/me").status_code == 200
    signed_in.post("/auth/logout")
    assert signed_in.get("/auth/me").status_code == 401


# -- the flow ------------------------------------------------------------
def test_status_reports_the_redirect_it_will_use(client, monkeypatch):
    """A mismatch with the console is the failure this project hits most, and
    it is otherwise invisible until the browser is already at Google."""
    monkeypatch.setenv("VS_AUTH_REDIRECT", "https://example.com/auth/callback")
    body = client.get("/auth/status").json()
    assert body["redirect_uri"] == "https://example.com/auth/callback"
    assert body["signed_in"] is False


def test_login_without_an_oauth_client_is_a_400_not_a_500(client, monkeypatch):
    from pathlib import Path

    from vsmail.gmail import client as gmail_client

    monkeypatch.delenv("VS_GMAIL_CREDENTIALS_JSON", raising=False)
    monkeypatch.setattr(gmail_client, "CREDENTIALS", Path("no-such-file.json"))
    assert client.get("/auth/login").status_code == 400


def test_an_unknown_state_does_not_sign_anybody_in(client):
    """The callback's only guard. A code presented with a state we never
    minted must not become a session."""
    response = client.get(
        "/auth/callback?code=whatever&state=never-issued", follow_redirects=False
    )
    assert response.status_code == 307
    assert "signin=expired" in response.headers["location"]
    assert session.COOKIE not in response.cookies


def test_a_completed_sign_in_sets_a_session(client, monkeypatch):
    from api import auth_routes

    monkeypatch.setattr(
        auth_routes.identity,
        "exchange",
        lambda code, state, verifier: Identity(email="her@example.com", name="Her"),
    )
    auth_routes._PENDING["st8"] = (__import__("time").time(), "verifier")

    response = client.get(
        "/auth/callback?code=good&state=st8", follow_redirects=False
    )
    assert "signin=ok" in response.headers["location"]
    assert session.verify(response.cookies[session.COOKIE])["email"] == "her@example.com"


def test_the_state_is_single_use(client, monkeypatch):
    """Replaying a callback must not mint a second session."""
    from api import auth_routes

    monkeypatch.setattr(
        auth_routes.identity,
        "exchange",
        lambda code, state, verifier: Identity(email="her@example.com"),
    )
    auth_routes._PENDING["once"] = (__import__("time").time(), "verifier")

    client.get("/auth/callback?code=good&state=once", follow_redirects=False)
    again = client.get("/auth/callback?code=good&state=once", follow_redirects=False)
    assert "signin=expired" in again.headers["location"]
