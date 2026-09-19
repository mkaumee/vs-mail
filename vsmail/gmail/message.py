"""Turning an EmailRecord into a Gmail message, and back again.

The round trip has to be lossless in one respect above all: the submission is
keyed by the bundle's own ids, so `email_004` has to survive going into Gmail
and coming back. A Gmail message id is not a substitute, which is why every
seeded message carries `X-VS-Email-Id`.

A message that lacks that header was genuinely delivered rather than seeded,
and gets an id derived from Gmail's own so it flows through the same pipeline.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, parsedate_to_datetime

from vsmail.models import EmailRecord

#: Carries the bundle's id across the round trip.
ID_HEADER = "X-VS-Email-Id"

#: Marks a message this system put there, so a reset knows what to remove.
SEED_HEADER = "X-VS-Seed"

#: An attachment inside a Gmail message. It ends in the original filename so
#: `role_from_path` and `attachment_for` keep resolving the SI and BL slots
#: from the filename, exactly as they do for a local path.
_URI = re.compile(r"^gmail://(?P<message>[^/]+)/(?P<attachment>[^/]+)/(?P<name>.+)$")

_FALLBACK_TYPE = ("application", "octet-stream")


def attachment_uri(message_id: str, attachment_id: str, filename: str) -> str:
    return f"gmail://{message_id}/{attachment_id}/{filename}"


def parse_attachment_uri(uri: str) -> tuple[str, str, str]:
    match = _URI.match(uri)
    if not match:
        raise ValueError(f"not a Gmail attachment reference: {uri!r}")
    return match["message"], match["attachment"], match["name"]


def _mime_type(filename: str) -> tuple[str, str]:
    guessed, _ = mimetypes.guess_type(filename)
    if not guessed or "/" not in guessed:
        return _FALLBACK_TYPE
    main, _, sub = guessed.partition("/")
    return main, sub


def build_mime(
    record: EmailRecord,
    attachments: list[tuple[str, bytes]],
    to: str,
    sent_at: datetime | None = None,
) -> EmailMessage:
    """Compose one seeded message.

    `From` is the bundle's original sender, which only insertion can preserve:
    genuinely sending would rewrite it to the sending account and cost the
    classifier a signal it uses.
    """
    message = EmailMessage()
    message[ID_HEADER] = record.email_id
    message[SEED_HEADER] = "1"
    message["From"] = record.sender or "unknown@example.invalid"
    message["To"] = to
    message["Subject"] = record.subject
    message["Date"] = format_datetime(sent_at or datetime.now(timezone.utc))
    message.set_content(record.body or "")

    for filename, data in attachments:
        main, sub = _mime_type(filename)
        message.add_attachment(data, maintype=main, subtype=sub, filename=filename)
    return message


def spread_dates(count: int, days: int = 14) -> list[datetime]:
    """Distinct, ordered timestamps over the recent past.

    The bundle carries no dates. Without this every message arrives in the
    same second, which makes the mailbox unreadable and hides ordering.
    """
    now = datetime.now(timezone.utc)
    step = timedelta(days=days) / max(count, 1)
    return [now - step * (count - index) for index in range(count)]


def encode(message: EmailMessage) -> str:
    """base64url, as the Gmail API expects a raw message."""
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _walk(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk(child)


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def to_record(message: dict) -> EmailRecord:
    """Rebuild an EmailRecord from a Gmail message resource.

    Accepts both seeded messages and genuinely delivered ones; the difference
    is only where the id comes from.
    """
    payload = message.get("payload", {}) or {}
    headers = _headers(payload)
    message_id = message.get("id", "")

    body_parts: list[str] = []
    attachments: list[str] = []
    for part in _walk(payload):
        filename = part.get("filename") or ""
        body = part.get("body", {}) or {}
        if filename and body.get("attachmentId"):
            attachments.append(attachment_uri(message_id, body["attachmentId"], filename))
        elif part.get("mimeType") == "text/plain" and body.get("data"):
            body_parts.append(_decode_body(body["data"]))

    if not body_parts and (payload.get("body") or {}).get("data"):
        body_parts.append(_decode_body(payload["body"]["data"]))

    return EmailRecord(
        # A delivered message has no seeded id, so Gmail's own is used. It is
        # prefixed to stay obviously distinct from the bundle's ids.
        email_id=headers.get(ID_HEADER.lower()) or f"gmail_{message_id}",
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        body="\n".join(body_parts).strip(),
        attachments=tuple(attachments),
    )


def received_at(message: dict) -> datetime | None:
    """When a message says it was sent, for ordering a live feed."""
    raw = _headers(message.get("payload", {}) or {}).get("date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def basename(uri: str) -> str:
    return os.path.basename(uri)
