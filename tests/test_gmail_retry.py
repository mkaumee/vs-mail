"""Temporary Gmail failures get a bounded, useful recovery path."""
import pytest

from vsmail.gmail import retry


class Failure(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.resp = type("Response", (), {"status": status})()
        self.content = detail.encode()


class Request:
    def __init__(self, failures: list[Exception]):
        self.failures = failures
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return {"ok": True}


def test_a_quota_403_is_retried(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda delay: None)
    request = Request([Failure(403, "rateLimitExceeded: Quota exceeded")])
    assert retry.execute(request, delays=(0,)) == {"ok": True}
    assert request.calls == 2


def test_a_permanent_403_is_not_retried(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda delay: None)
    request = Request([Failure(403, "insufficientPermissions")])
    with pytest.raises(Failure):
        retry.execute(request, delays=(0, 0))
    assert request.calls == 1


def test_exhausted_quota_has_an_actionable_error(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda delay: None)
    request = Request([Failure(429, "quota") for _ in range(3)])
    with pytest.raises(retry.GmailTemporarilyBusy, match="Wait about a minute"):
        retry.execute(request, delays=(0, 0))


def test_mailbox_profile_is_cached(monkeypatch):
    from tests.gmail_fake import FakeGmail
    from vsmail.gmail import client

    monkeypatch.setattr(client, "_ADDRESS_CACHE", None)
    gmail = FakeGmail()

    assert client.address(gmail) == "ops@example.test"
    assert client.address(gmail) == "ops@example.test"
    assert gmail.profile_calls == 1
