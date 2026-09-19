"""Reading a real mailbox as if it were the bundle.

Everything downstream touches an inbox through three methods — `emails()`,
`get()` and `read_bytes()` — so offering the same three is the entire
integration surface. The pipeline, the API and every script work unchanged.

The mailbox is read with `in:anywhere`, **including Spam**. If Gmail's own
filter misfiles something, that is exactly the email an ops desk still has to
deal with, and a system whose job includes recognising spam should be looking
where spam actually lands rather than relying on Google having already sorted
it.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from vsmail.gmail.message import parse_attachment_uri, to_record
from vsmail.models import EmailRecord

#: Everything in the mailbox: inbox, archive, spam and bin alike.
DEFAULT_QUERY = "in:anywhere"

#: Fetching 520 messages and their attachments takes minutes over HTTP
#: against under a second from disk, and nothing about a seeded message
#: changes between runs.
CACHE = Path(os.environ.get("VS_GMAIL_CACHE", ".gmail-cache"))


class GmailSource:
    """A Gmail mailbox, shaped like `vsmail.inbox.Bundle`."""

    def __init__(self, service, query: str = DEFAULT_QUERY, cache: Path | None = None):
        self.service = service
        self.query = query
        self.cache = Path(cache) if cache is not None else CACHE
        self._records: list[EmailRecord] | None = None

    # -- listing ---------------------------------------------------------
    def message_ids(self) -> list[str]:
        ids: list[str] = []
        token = None
        while True:
            response = (
                self.service.users()
                .messages()
                .list(userId="me", q=self.query, pageToken=token, maxResults=500)
                .execute()
            )
            ids.extend(m["id"] for m in response.get("messages", []) or [])
            token = response.get("nextPageToken")
            if not token:
                break
        return ids

    def _message(self, message_id: str) -> dict:
        cached = self.cache / "messages" / f"{message_id}.json"
        if cached.is_file():
            return json.loads(cached.read_text())
        message = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(message))
        return message

    def emails(self) -> list[EmailRecord]:
        if self._records is None:
            self._records = [to_record(self._message(mid)) for mid in self.message_ids()]
        return self._records

    def get(self, email_id: str) -> EmailRecord:
        for record in self.emails():
            if record.email_id == email_id:
                return record
        raise KeyError(f"no message in the mailbox for {email_id}")

    # -- attachments -----------------------------------------------------
    def read_bytes(self, attachment_path: str) -> bytes:
        message_id, attachment_id, _ = parse_attachment_uri(attachment_path)
        cached = self.cache / "attachments" / message_id / attachment_id
        if cached.is_file():
            return cached.read_bytes()

        response = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = base64.urlsafe_b64decode(response["data"].encode())
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        return data

    # -- the bundle offers these; a mailbox has no equivalent ------------
    def sample_submission(self) -> dict:
        from vsmail.inbox import Bundle

        return Bundle().sample_submission()

    def message_id_for(self, email_id: str) -> str | None:
        """The Gmail id behind a record, for writing labels back."""
        for message_id in self.message_ids():
            record = to_record(self._message(message_id))
            if record.email_id == email_id:
                return message_id
        return None
