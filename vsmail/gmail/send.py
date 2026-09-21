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

from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path

from vsmail.gmail.message import encode
from vsmail.gmail.retry import execute


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
    sent = execute(
        service.users()
        .messages()
        .send(userId="me", body={"raw": encode(message)})
    )
    return sent["id"]


#: Set this and every reply goes here instead of to the customer. It is the
#: safety default for a deployment: a demo that emails a real freight desk is
#: worse than a demo that sends nothing at all.
TEST_RECIPIENT_ENV = "VS_TEST_RECIPIENT"

#: Prepended to a diverted body, so the address it was meant for is visible in
#: the message itself rather than only in a header nobody opens.
BANNER = "[TEST SEND — this would have gone to {real}]"


class RefusedToSend(RuntimeError):
    """No test recipient, and nobody said to use the real address."""


def test_recipient(supplied: str | None = None) -> str:
    """The address replies are diverted to, from the request or the environment.

    The request wins so a person can change it without a redeploy; the
    environment is what pins a deployment safe when the page sends nothing.
    """
    import os

    return (supplied or os.environ.get(TEST_RECIPIENT_ENV, "")).strip()


def redirect(to: str, diverted_to: str) -> tuple[str, str | None]:
    """Where the mail actually goes, and the address it was taken from.

    Returns `(recipient, diverted_from)`. `diverted_from` is None when the
    mail is going where it says, which is what the caller reports on screen.
    """
    if not diverted_to:
        return to, None
    return diverted_to, to


def send_reply(
    service,
    draft,
    gmail_message_id: str | None = None,
    supplied_recipient: str | None = None,
    allow_real: bool = False,
) -> dict:
    """Send a reply, diverted to the test address unless told otherwise.

    The guard lives here rather than in the page because the page can be a
    stale tab. This is the only thing in the system that can put mail in front
    of a third party, so refusing is the default and reaching a customer takes
    a deliberate `allow_real`.

    Threading is `drafts.build`'s, so a sent reply lands in the original
    conversation exactly as a saved draft would.
    """
    from vsmail.gmail import drafts

    diverted_to = test_recipient(supplied_recipient)
    if not diverted_to and not allow_real:
        raise RefusedToSend(
            "No test recipient is set, so this would go to the address on the "
            f"email. Set one, or pass allow_real to send to {draft.to!r}."
        )

    recipient, diverted_from = redirect(draft.to, diverted_to)

    thread_id, message_id = (None, None)
    if gmail_message_id:
        thread_id, message_id = drafts._original(service, gmail_message_id)

    body = draft.body
    if diverted_from:
        body = f"{BANNER.format(real=diverted_from)}\n\n{body}"

    message = drafts.build(replace(draft, to=recipient, body=body), message_id)
    if diverted_from:
        message["X-VS-Would-Have-Gone-To"] = diverted_from

    payload: dict = {"raw": encode(message)}
    if thread_id:
        payload["threadId"] = thread_id

    sent = execute(service.users().messages().send(userId="me", body=payload))
    return {
        "message_id": sent["id"],
        "sent_to": recipient,
        "diverted_from": diverted_from,
        "threaded": bool(thread_id),
    }
