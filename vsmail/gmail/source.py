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

import json
import os
import tempfile
import threading
from pathlib import Path

from vsmail.gmail.message import (
    decode_data,
    inline_attachment_data,
    parse_attachment_uri,
    to_record,
)
from vsmail.gmail.retry import execute
from vsmail.models import EmailRecord

#: Every live message, including Spam. Trash is excluded so resetting seeded
#: data actually removes it from processing.
DEFAULT_QUERY = "in:anywhere -in:trash"

#: Fetching 520 messages and their attachments takes minutes over HTTP
#: against under a second from disk, and nothing about a seeded message
#: changes between runs.
CACHE = Path(os.environ.get("VS_GMAIL_CACHE", ".gmail-cache"))


def _atomic_write(path: Path, data: bytes) -> None:
    """Publish a complete cache entry even when two card requests race."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temp_path = Path(temporary)
    try:
        temp_path.write_bytes(data)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


class GmailSource:
    """A Gmail mailbox, shaped like `vsmail.inbox.Bundle`."""

    def __init__(self, service, query: str = DEFAULT_QUERY, cache: Path | None = None):
        self.service = service
        self.query = query
        self.cache = Path(cache) if cache is not None else CACHE
        self._records: list[EmailRecord] | None = None
        self._records_complete = False
        self._message_ids: dict[str, str] = {}
        # googleapiclient shares one httplib2 transport, which is not safe to
        # use concurrently. Document reads run in worker threads so the web
        # server stays responsive; this lock keeps their network calls serial.
        self._api_lock = threading.Lock()

    # -- listing ---------------------------------------------------------
    def message_ids(self, limit: int | None = None) -> list[str]:
        ids: list[str] = []
        token = None
        while True:
            remaining = None if limit is None else limit - len(ids)
            if remaining is not None and remaining <= 0:
                break
            with self._api_lock:
                response = execute(
                    self.service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=self.query,
                        pageToken=token,
                        maxResults=min(500, remaining) if remaining is not None else 500,
                        includeSpamTrash=True,
                    )
                )
            ids.extend(m["id"] for m in response.get("messages", []) or [])
            if limit is not None:
                ids = ids[:limit]
            token = response.get("nextPageToken")
            if not token or (limit is not None and len(ids) >= limit):
                break
        return ids

    def _message(self, message_id: str) -> dict:
        cached = self.cache / "messages" / f"{message_id}.json"
        if cached.is_file():
            try:
                return json.loads(cached.read_text())
            except (OSError, json.JSONDecodeError):
                # An interrupted older process may have left a partial file.
                # Fetching again is safer than turning it into a broken card.
                pass
        with self._api_lock:
            message = execute(
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
            )
        _atomic_write(cached, json.dumps(message).encode())
        return message

    def emails(self, limit: int | None = None) -> list[EmailRecord]:
        enough_cached = self._records is not None and (
            self._records_complete or (limit is not None and len(self._records) >= limit)
        )
        if not enough_cached:
            ids = self.message_ids(limit)
            self._records = [self.get_message(message_id) for message_id in ids]
            self._records_complete = limit is None or len(ids) < limit
        return self._records if limit is None else self._records[:limit]

    def get_message(self, message_id: str) -> EmailRecord:
        """Read one known Gmail message without listing the whole mailbox."""
        record = to_record(self._message(message_id))
        self._message_ids[record.email_id] = message_id
        return record

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

        if attachment_id.startswith("inline-"):
            # The full message already contains these bytes, so this normally
            # reads the message cache and costs no extra Gmail API request.
            data = inline_attachment_data(self._message(message_id), attachment_id)
        else:
            with self._api_lock:
                response = execute(
                    self.service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=message_id, id=attachment_id)
                )
            data = decode_data(response["data"])
        _atomic_write(cached, data)
        return data

    # -- the bundle offers these; a mailbox has no equivalent ------------
    def sample_submission(self) -> dict:
        from vsmail.inbox import Bundle

        return Bundle().sample_submission()

    def message_id_for(self, email_id: str) -> str | None:
        """The Gmail id behind a record, for writing labels back."""
        if self._records is None:
            self.emails()
        return self._message_ids.get(email_id)
