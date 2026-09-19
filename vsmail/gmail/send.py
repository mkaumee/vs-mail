"""Sending mail that is genuinely delivered.

The dataset is inserted, because only insertion preserves its senders. This
is the other half: a message that actually travels, arrives on its own, and
is picked up by the watcher like any other mail. It is what makes the live
demo real rather than staged.

Two things cannot be worked around. The sender will be whichever account
sent it — forging a `From` is what SPF and DKIM exist to prevent. And
spam-shaped content sent from a real account risks that account's standing,
which is why the bundle's spam samples are inserted rather than sent.
"""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from vsmail.gmail.message import encode


def compose(
    to: str,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
) -> EmailMessage:
    import mimetypes

    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    for path in attachments or []:
        data = Path(path).read_bytes()
        guessed, _ = mimetypes.guess_type(str(path))
        main, _, sub = (guessed or "application/octet-stream").partition("/")
        message.add_attachment(
            data, maintype=main, subtype=sub or "octet-stream", filename=Path(path).name
        )
    return message


def send(service, message: EmailMessage) -> str:
    """Hand a message to Gmail for real delivery. Returns its message id."""
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": encode(message)})
        .execute()
    )
    return sent["id"]
