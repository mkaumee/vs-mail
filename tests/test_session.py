"""The signed cookie that says who is signed in.

The email in this payload is the identity every route downstream believes, so
the interesting tests are the ones where it must be refused.
"""
from __future__ import annotations

import time

import pytest

from vsmail import session
from vsmail.session import BadSession, sign, verify


@pytest.fixture(autouse=True)
def a_secret(monkeypatch):
    monkeypatch.setenv("VS_SERVICE_TOKEN", "a" * 40)
    monkeypatch.delenv(session.SECRET_ENV, raising=False)


def test_a_signed_payload_comes_back():
    assert verify(sign({"email": "me@example.com"}))["email"] == "me@example.com"


def test_an_altered_payload_is_refused():
    """The whole job. An editable cookie is an editable identity."""
    import base64, json

    raw = json.dumps(
        {"email": "someone-else@example.com", "exp": int(time.time()) + 600},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    forged = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    _, _, signature = sign({"email": "me@example.com"}).partition(".")

    with pytest.raises(BadSession, match="signature"):
        verify(f"{forged}.{signature}")


def test_an_expired_payload_is_refused_despite_a_good_signature():
    """Leaving this to the cookie's Max-Age would trust the browser to do it."""
    with pytest.raises(BadSession, match="expired"):
        verify(sign({"email": "me@example.com"}, lifetime=-1))


def test_nonsense_is_refused_rather_than_raising_something_else():
    for value in ("", "no-dot", "!!!.???"):
        with pytest.raises(BadSession):
            verify(value)


def test_a_different_secret_does_not_verify(monkeypatch):
    """Rotating the secret signs everyone out, which is the point of having one."""
    cookie = sign({"email": "me@example.com"})
    monkeypatch.setenv(session.SECRET_ENV, "b" * 40)
    with pytest.raises(BadSession):
        verify(cookie)


def test_no_secret_refuses_rather_than_signing_with_a_default(monkeypatch):
    """A shared default would mean every deployment of this code could forge
    every other one's sessions."""
    monkeypatch.delenv("VS_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv(session.SECRET_ENV, raising=False)
    with pytest.raises(BadSession, match="no signing secret"):
        sign({"email": "me@example.com"})
