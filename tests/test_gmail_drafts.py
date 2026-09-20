"""Putting a reply into Gmail, unsent.

Two things matter: that it is a draft and not a send, and that it lands in the
conversation it belongs to. A correction arriving as a fresh thread has to be
matched back to the shipment by hand, which is the work being saved.
"""
from email.message import EmailMessage

from tests.gmail_fake import FakeGmail, as_message
from vsmail.gmail import drafts as gmail_drafts
from vsmail.reply import Draft

DRAFT = Draft(
    to="hari@aprilasia.com",
    subject="RE: TO CONFIRM DOCS _ 5RFR-36884",
    body="Dear Hari,\n\nConsignee does not agree.\n\nThanks,",
    kind="mismatch",
)


def mailbox() -> FakeGmail:
    original = EmailMessage()
    original["From"] = "hari@aprilasia.com"
    original["Subject"] = "TO CONFIRM DOCS _ 5RFR-36884"
    original["Message-ID"] = "<abc123@mail.aprilasia.com>"
    original.set_content("Please check.")
    return FakeGmail({"MSG1": as_message(original, "MSG1")})


def test_it_creates_a_draft_and_never_sends():
    gmail = mailbox()
    gmail_drafts.create(gmail, DRAFT, "MSG1")
    assert len(gmail.drafts_created) == 1
    assert gmail.sent == []


def test_the_draft_joins_the_original_thread():
    gmail = mailbox()
    result = gmail_drafts.create(gmail, DRAFT, "MSG1")
    assert result["threaded"] is True
    assert gmail.drafts_created[0]["message"]["threadId"] == "MSG1"


def test_it_carries_the_reply_headers_other_clients_need():
    """Gmail threads on threadId; everything else in the chain reads
    In-Reply-To."""
    built = gmail_drafts.build(DRAFT, "<abc123@mail.aprilasia.com>")
    assert built["In-Reply-To"] == "<abc123@mail.aprilasia.com>"
    assert built["References"] == "<abc123@mail.aprilasia.com>"
    assert built["To"] == "hari@aprilasia.com"


def test_an_email_that_never_came_from_gmail_still_drafts():
    """A bundle email has no Gmail id. Refusing would withhold the text, which
    is the valuable part; it is simply not threaded."""
    gmail = mailbox()
    result = gmail_drafts.create(gmail, DRAFT, None)
    assert result["threaded"] is False
    assert "threadId" not in gmail.drafts_created[0]["message"]
    assert len(gmail.drafts_created) == 1


def test_the_body_survives_encoding():
    import base64

    gmail = mailbox()
    gmail_drafts.create(gmail, DRAFT, "MSG1")
    raw = gmail.drafts_created[0]["message"]["raw"]
    decoded = base64.urlsafe_b64decode(raw).decode()
    assert "Consignee does not agree." in decoded
