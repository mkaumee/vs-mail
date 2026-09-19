"""Access to the organizers' bundle.

Wraps the `loader.Inbox` shipped with the bundle rather than reimplementing
inbox access, so we read the data exactly the way the official scoring run
does. The loader takes either a folder or an HTTP base URL; both work here.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

from vsmail.models import EmailRecord

#: The bundle as checked into this repository.
DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "sample data"


@lru_cache(maxsize=1)
def _sdoc_loader():
    """Import the bundle's own loader.py.

    It lives in a directory whose name contains a space, so it cannot be
    imported by name.
    """
    path = DEFAULT_SOURCE / "loader.py"
    spec = importlib.util.spec_from_file_location("sdoc_loader", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"could not load the bundle loader at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Bundle:
    """The 520-email inbox, from a local folder or the scoring server."""

    def __init__(self, source: str | Path = DEFAULT_SOURCE):
        self.source = str(source)
        self._inbox = _sdoc_loader().Inbox(self.source)

    def emails(self) -> list[EmailRecord]:
        return [EmailRecord.from_json(record) for record in self._inbox.emails()]

    def get(self, email_id: str) -> EmailRecord:
        return EmailRecord.from_json(self._inbox.get(email_id))

    def read_bytes(self, attachment_path: str) -> bytes:
        return self._inbox.read_bytes(attachment_path)

    def sample_submission(self) -> dict:
        return self._inbox.sample_submission()

    def submit(self, submission: dict) -> dict:
        """POST a submission to a scoring server. HTTP sources only."""
        return self._inbox.submit(submission)
