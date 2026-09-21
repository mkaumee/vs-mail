"""A stand-in for the Gmail API, so tests need no network or credentials.

Only the tests use this. The running system always talks to the real API.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage


def as_payload(message: EmailMessage) -> dict:
    """Render a composed message the way `messages.get(format="full")` does."""
    headers = [{"name": k, "value": v} for k, v in message.items()]

    def part_of(part: EmailMessage, index: int) -> dict:
        filename = part.get_filename()
        content = part.get_payload(decode=True) or b""
        body: dict = {"size": len(content)}
        if filename:
            # Gmail withholds attachment bytes and gives an id to fetch them.
            body["attachmentId"] = f"att{index}"
        else:
            body["data"] = base64.urlsafe_b64encode(content).decode()
        return {
            "mimeType": part.get_content_type(),
            "filename": filename or "",
            "body": body,
        }

    if message.is_multipart():
        parts = [part_of(p, i) for i, p in enumerate(message.iter_parts())]
        return {"headers": headers, "mimeType": "multipart/mixed", "parts": parts}
    return {"headers": headers, **part_of(message, 0)}


def as_message(message: EmailMessage, message_id: str = "MSG1") -> dict:
    return {"id": message_id, "threadId": message_id, "payload": as_payload(message)}


class FakeGmail:
    """Enough of the API surface for GmailSource and the label writer.

    Records what was asked of it so tests can assert on the calls, not just
    the results.
    """

    def __init__(self, messages: dict[str, dict] | None = None):
        self.store = messages or {}
        self.attachments: dict[tuple[str, str], bytes] = {}
        self.label_calls: list[tuple[str, list[str]]] = []
        self.inserted: list[dict] = []
        self.sent: list[dict] = []
        self.drafts_created: list[dict] = []
        self.deleted: list[str] = []
        self.labels: dict[str, str] = {}
        self.queries: list[str] = []
        self.include_spam_trash: list[bool] = []

    # -- the shape googleapiclient exposes ------------------------------
    def users(self):
        return _Users(self)


class _Users:
    """Kept separate so the message store and the messages() call cannot
    collide on a name, which is exactly what the real client avoids too."""

    def __init__(self, gmail: "FakeGmail"):
        self.gmail = gmail

    def getProfile(self, userId):
        return _Result({"emailAddress": "ops@example.test"})

    def messages(self):
        return _Messages(self.gmail)

    def drafts(self):
        return _Drafts(self.gmail)

    def labels(self):
        return _Labels(self.gmail)


class _Drafts:
    def __init__(self, gmail: "FakeGmail"):
        self.gmail = gmail

    def create(self, userId, body):
        self.gmail.drafts_created.append(body)
        return _Result({"id": f"draft{len(self.gmail.drafts_created)}"})


class _Result:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _Messages:
    def __init__(self, gmail: FakeGmail):
        self.gmail = gmail

    def list(
        self,
        userId,
        q=None,
        pageToken=None,
        maxResults=None,
        includeSpamTrash=False,
    ):
        self.gmail.queries.append(q or "")
        self.gmail.include_spam_trash.append(includeSpamTrash)
        return _Result({"messages": [{"id": k} for k in self.gmail.store]})

    def get(self, userId, id, format=None, metadataHeaders=None):
        return _Result(self.gmail.store[id])

    def insert(self, userId, body, internalDateSource=None):
        self.gmail.inserted.append(body)
        from email import policy
        from email.parser import BytesParser

        message_id = f"ins{len(self.gmail.inserted)}"
        raw = base64.urlsafe_b64decode(body["raw"].encode())
        message = BytesParser(policy=policy.default).parsebytes(raw)
        self.gmail.store[message_id] = as_message(message, message_id)
        return _Result({"id": message_id})

    def send(self, userId, body):
        self.gmail.sent.append(body)
        return _Result({"id": f"snt{len(self.gmail.sent)}"})

    def delete(self, userId, id):
        self.gmail.deleted.append(id)
        return _Result({})

    def trash(self, userId, id):
        self.gmail.deleted.append(id)
        return _Result({})

    def modify(self, userId, id, body):
        self.gmail.label_calls.append((id, body.get("addLabelIds", [])))
        return _Result({})

    def attachments(self):
        return _Attachments(self.gmail)


class _Attachments:
    def __init__(self, gmail: FakeGmail):
        self.gmail = gmail

    def get(self, userId, messageId, id):
        import base64 as b64

        data = self.gmail.attachments.get((messageId, id), b"")
        return _Result({"data": b64.urlsafe_b64encode(data).decode()})


class _Labels:
    def __init__(self, gmail: FakeGmail):
        self.gmail = gmail

    def list(self, userId):
        return _Result(
            {"labels": [{"id": v, "name": k} for k, v in self.gmail.labels.items()]}
        )

    def create(self, userId, body):
        name = body["name"]
        self.gmail.labels[name] = f"Label_{len(self.gmail.labels) + 1}"
        return _Result({"id": self.gmail.labels[name], "name": name})
