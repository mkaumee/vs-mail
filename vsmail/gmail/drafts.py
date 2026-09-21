"""Putting a drafted reply into Gmail itself, unsent.

A draft rather than a send, and that is the feature rather than a limitation.
The system proposes the words; a person reads them and presses send. Nothing
here can put mail in front of a customer on its own.

Threading is the part worth getting right. A correction that arrives as a new
conversation has to be matched back to the shipment by hand, which is exactly
the work this is meant to save — so the draft carries Gmail's `threadId` and
the RFC-822 `In-Reply-To`/`References` headers pointing at the original.
Gmail needs the thread id; other clients in the chain need the headers.
"""
from __future__ import annotations

from email.message import EmailMessage

from vsmail.gmail.message import encode
from vsmail.gmail.retry import execute


def _original(service, message_id: str) -> tuple[str, str | None]:
    """The thread this message belongs to, and its RFC-822 Message-ID."""
    message = execute(
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="metadata",
             metadataHeaders=["Message-ID", "Subject"])
    )
    headers = {
        h["name"].lower(): h["value"]
        for h in message.get("payload", {}).get("headers", [])
    }
    return message["threadId"], headers.get("message-id")


def build(draft, in_reply_to: str | None = None) -> EmailMessage:
    """A reply as MIME, threaded onto the original where we know its id."""
    message = EmailMessage()
    message["To"] = draft.to
    message["Subject"] = draft.subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
    message.set_content(draft.body)
    return message


def create(service, draft, gmail_message_id: str | None) -> dict:
    """Create the draft in Gmail. Returns its id and the thread it joined.

    Without a Gmail message id — the email came from the bundle's files rather
    than a mailbox — the draft is still created, just not threaded. Saying so
    is better than refusing: the text is the valuable part.
    """
    thread_id, message_id = (None, None)
    if gmail_message_id:
        thread_id, message_id = _original(service, gmail_message_id)

    body: dict = {"message": {"raw": encode(build(draft, message_id))}}
    if thread_id:
        body["message"]["threadId"] = thread_id

    created = execute(service.users().drafts().create(userId="me", body=body))
    return {
        "draft_id": created["id"],
        "thread_id": thread_id,
        "threaded": bool(thread_id),
    }
