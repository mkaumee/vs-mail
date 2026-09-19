"""Loading the bundle into a real mailbox.

`users.messages.insert` is the Gmail API's equivalent of IMAP APPEND — what
mailbox migration tools use. The messages genuinely exist in the mailbox and
are genuinely read back over the API.

It is used here for fidelity. The bundle's emails come from dozens of
senders, and real delivery cannot preserve those: SPF and DKIM exist to stop
forged senders, so genuinely sent mail arrives from whatever account sent it.
That would cost the classifier a signal it uses, on all 520 emails.
"""
from __future__ import annotations

import time

from vsmail.gmail.client import address
from vsmail.gmail.labels import SEED_LABEL, Labels
from vsmail.gmail.message import build_mime, encode, spread_dates
from vsmail.inbox import Bundle

#: `insert` costs 25 quota units against a 250-per-second ceiling, so about
#: ten a second is the hard limit. Eight leaves room for the label calls.
PER_SECOND = 8.0

#: Retries on a rate-limit response, backing off each time.
RETRIES = 4


def _with_retries(call):
    delay = 1.0
    for attempt in range(RETRIES):
        try:
            return call()
        except Exception as exc:  # googleapiclient raises HttpError
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status not in (403, 429, 500, 503) or attempt == RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")  # pragma: no cover


def seed(service, bundle: Bundle | None = None, limit: int | None = None) -> dict:
    """Insert the bundle's emails, preserving sender, subject and body."""
    bundle = bundle or Bundle()
    emails = bundle.emails()
    if limit:
        emails = emails[:limit]

    labels = Labels(service)
    seed_label = labels.id_for(SEED_LABEL)
    mailbox = address(service)
    dates = spread_dates(len(emails))

    inserted, failed = 0, []
    interval = 1.0 / PER_SECOND
    for email, sent_at in zip(emails, dates):
        attachments = []
        for path in email.attachments:
            try:
                attachments.append((path.split("/")[-1], bundle.read_bytes(path)))
            except Exception as exc:
                failed.append((email.email_id, f"attachment {path}: {exc}"))
        try:
            started = time.monotonic()
            _with_retries(
                lambda: service.users()
                .messages()
                .insert(
                    userId="me",
                    body={
                        "raw": encode(build_mime(email, attachments, mailbox, sent_at)),
                        # INBOX so it looks like arrived mail; UNREAD so the
                        # mailbox reads like a morning's work.
                        "labelIds": ["INBOX", "UNREAD", seed_label],
                    },
                    # Without this every message takes the insertion time and
                    # the whole mailbox collapses into one second.
                    internalDateSource="dateHeader",
                )
                .execute()
            )
            inserted += 1
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
        except Exception as exc:
            failed.append((email.email_id, str(exc)))

    return {"mailbox": mailbox, "inserted": inserted, "failed": failed}


def reset(service) -> dict:
    """Move everything this system seeded to the bin.

    Trashed rather than deleted: `messages.delete` needs full-mailbox scope,
    and an irreversible bulk delete is not something to hold the permission
    for. Anything removed here can be recovered from Gmail's bin.
    """
    labels = Labels(service)
    seed_label = labels.id_for(SEED_LABEL)

    trashed = 0
    while True:
        listed = (
            service.users()
            .messages()
            .list(userId="me", q=f"label:{SEED_LABEL}", maxResults=500)
            .execute()
        )
        ids = [m["id"] for m in listed.get("messages", [])]
        if not ids:
            break
        for message_id in ids:
            _with_retries(
                lambda mid=message_id: service.users()
                .messages()
                .trash(userId="me", id=mid)
                .execute()
            )
            trashed += 1
        if not listed.get("nextPageToken"):
            break

    return {"trashed": trashed, "label": seed_label}
