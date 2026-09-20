"""Sending a reply, and refusing to.

This is the only thing in the system that can put mail in front of a third
party. The bundle's senders are real-looking addresses at real-looking
companies, so the interesting assertions here are the ones about mail that
must *not* go anywhere.
"""
from __future__ import annotations

import base64

import pytest

from tests.gmail_fake import FakeGmail, as_message
from vsmail.gmail import send as sending
from vsmail.gmail.send import RefusedToSend, send_reply
from vsmail.reply import Draft


def a_draft(to: str = "docs@vitalsolutions.sg") -> Draft:
    return Draft(
        to=to,
        subject="RE: REQUEST BL DRAFT",
        body="Dear Team,\n\nConsignee does not agree.\n\nThanks,",
        kind="mismatch",
    )


def decoded(raw: str) -> str:
    return base64.urlsafe_b64decode(raw.encode()).decode()


@pytest.fixture(autouse=True)
def no_ambient_recipient(monkeypatch):
    """The environment must not leak a test address into these assertions."""
    monkeypatch.delenv(sending.TEST_RECIPIENT_ENV, raising=False)


def test_refuses_without_a_test_recipient():
    """The default is that nothing is sent. Nothing must reach the API."""
    gmail = FakeGmail()
    with pytest.raises(RefusedToSend) as raised:
        send_reply(gmail, a_draft())

    assert "docs@vitalsolutions.sg" in str(raised.value)
    assert gmail.sent == [], "a refused send still reached Gmail"


def test_diverts_to_the_test_recipient():
    gmail = FakeGmail()
    result = send_reply(gmail, a_draft(), supplied_recipient="me@example.com")

    assert result["sent_to"] == "me@example.com"
    assert result["diverted_from"] == "docs@vitalsolutions.sg"

    body = decoded(gmail.sent[0]["raw"])
    # Anchored to the line: "X-VS-Would-Have-Gone-To: docs@..." carries the
    # same substring, and matching that would pass a mail addressed to them.
    headers = body.split("\n\n", 1)[0].splitlines()
    assert "To: me@example.com" in headers
    assert "To: docs@vitalsolutions.sg" not in headers, "addressed to the customer"


def test_the_real_address_survives_in_the_banner_and_header():
    """Diverted mail must still say who it was for, or it is untraceable."""
    gmail = FakeGmail()
    send_reply(gmail, a_draft(), supplied_recipient="me@example.com")

    body = decoded(gmail.sent[0]["raw"])
    assert "X-VS-Would-Have-Gone-To: docs@vitalsolutions.sg" in body
    assert "[TEST SEND — this would have gone to docs@vitalsolutions.sg]" in body
    # The reply itself is intact underneath the banner.
    assert "Consignee does not agree." in body


def test_the_environment_pins_a_deployment_safe(monkeypatch):
    """A page that sends no recipient still must not reach the customer."""
    monkeypatch.setenv(sending.TEST_RECIPIENT_ENV, "ops@example.com")
    gmail = FakeGmail()
    result = send_reply(gmail, a_draft())

    assert result["sent_to"] == "ops@example.com"


def test_allow_real_reaches_the_real_address():
    gmail = FakeGmail()
    result = send_reply(gmail, a_draft(), allow_real=True)

    assert result["sent_to"] == "docs@vitalsolutions.sg"
    assert result["diverted_from"] is None

    body = decoded(gmail.sent[0]["raw"])
    assert "To: docs@vitalsolutions.sg" in body
    assert "TEST SEND" not in body, "a real send must not carry the test banner"
    assert "X-VS-Would-Have-Gone-To" not in body


def test_a_sent_reply_threads_onto_the_original():
    """A correction that starts a new conversation has to be matched back by
    hand, which is the work this is meant to save."""
    original = as_message(_an_email(), message_id="MSG1")
    gmail = FakeGmail({"MSG1": original})

    result = send_reply(
        gmail, a_draft(), gmail_message_id="MSG1", supplied_recipient="me@example.com"
    )

    assert result["threaded"] is True
    assert gmail.sent[0]["threadId"] == "MSG1"
    body = decoded(gmail.sent[0]["raw"])
    assert "In-Reply-To: <orig@vitalsolutions.sg>" in body
    assert "References: <orig@vitalsolutions.sg>" in body


def test_a_bundle_email_still_sends_unthreaded():
    """No Gmail id — it came from the organizers' files — is not a refusal."""
    gmail = FakeGmail()
    result = send_reply(gmail, a_draft(), supplied_recipient="me@example.com")

    assert result["threaded"] is False
    assert "threadId" not in gmail.sent[0]


def _an_email():
    from email.message import EmailMessage

    message = EmailMessage()
    message["To"] = "us@example.com"
    message["From"] = "docs@vitalsolutions.sg"
    message["Subject"] = "REQUEST BL DRAFT"
    message["Message-ID"] = "<orig@vitalsolutions.sg>"
    message.set_content("Kindly check the draft.")
    return message
