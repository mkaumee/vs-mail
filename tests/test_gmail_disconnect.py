"""Detaching a mailbox.

Deleting our copy is not a disconnect — Google still trusts the grant, so
reconnecting skips consent and anyone holding a copy of the token can still
use it. These tests are mostly about the revoke actually being attempted, and
about the one case the app cannot fix saying so.
"""
from __future__ import annotations

import json

import pytest

from vsmail.gmail import client as gmail_client

A_TOKEN = {
    "token": "access",
    "refresh_token": "refresh-me",
    "client_id": "cid",
    "client_secret": "secret",
}


class _Posted:
    """Records the revoke call instead of making it."""

    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[dict] = []

    def __call__(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data})
        return type("R", (), {"status_code": self.status})()


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    path.write_text(json.dumps(A_TOKEN))
    monkeypatch.setattr(gmail_client, "TOKEN", path)
    monkeypatch.delenv(gmail_client.TOKEN_ENV, raising=False)
    return path


def test_it_revokes_at_google_and_removes_the_file(token_file, monkeypatch):
    import httpx

    posted = _Posted()
    monkeypatch.setattr(httpx, "post", posted)

    result = gmail_client.forget()

    assert result == {
        "revoked": True,
        "file_removed": True,
        "still_in_environment": False,
    }
    assert not token_file.exists()
    assert posted.calls[0]["url"] == "https://oauth2.googleapis.com/revoke"
    assert posted.calls[0]["data"] == {"token": "refresh-me"}


def test_an_already_dead_token_still_counts_as_revoked(token_file, monkeypatch):
    """Google answers 400 for a token that was already invalid. It cannot be
    used either way, which is what was asked for."""
    import httpx

    monkeypatch.setattr(httpx, "post", _Posted(status=400))
    assert gmail_client.forget()["revoked"] is True


def test_google_being_unreachable_still_removes_the_local_copy(token_file, monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", boom)
    result = gmail_client.forget()

    assert result["revoked"] is False
    assert result["file_removed"] is True
    assert not token_file.exists()


def test_a_token_held_in_the_environment_is_reported_not_hidden(tmp_path, monkeypatch):
    """A process cannot unset its deployment's variable. Saying so beats
    reporting a clean disconnect that did not happen."""
    import httpx

    monkeypatch.setattr(gmail_client, "TOKEN", tmp_path / "absent.json")
    monkeypatch.setenv(gmail_client.TOKEN_ENV, json.dumps(A_TOKEN))
    monkeypatch.setattr(httpx, "post", _Posted())

    result = gmail_client.forget()

    assert result["still_in_environment"] is True
    assert result["revoked"] is True, "the grant must die even if the value stays"
    assert result["file_removed"] is False


def test_disconnecting_when_nothing_is_connected_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(gmail_client, "TOKEN", tmp_path / "absent.json")
    monkeypatch.delenv(gmail_client.TOKEN_ENV, raising=False)

    assert gmail_client.forget() == {
        "revoked": False,
        "file_removed": False,
        "still_in_environment": False,
    }
