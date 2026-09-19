"""Attachment readers.

Every format resolves to the same `Document`, so nothing downstream needs to
know whether a value came from plain text, a PDF, a spreadsheet or a Word
file. Readers take bytes rather than a path so they work identically against
a local bundle and the HTTP loader.
"""
from __future__ import annotations

import os

from vsmail.models import Document
from vsmail.documents.base import DocumentUnreadable
from vsmail.documents.pdf import read_pdf
from vsmail.documents.text import read_text

__all__ = ["read_document", "role_from_path"]


def role_from_path(path: str) -> str:
    """Whether an attachment fills the SI or the BL slot.

    Taken from the filename only. The document's own heading is unreliable:
    `email_059_SI.pdf` and `email_208_SI.pdf` are both titled "BILL OF LADING
    INSTRUCTION" despite being shipping instructions.
    """
    name = os.path.basename(path).upper()
    if "_SI." in name:
        return "SI"
    if "_BL." in name:
        return "BL"
    return "UNKNOWN"


def read_document(path: str, data: bytes, role: str | None = None) -> Document:
    """Read one attachment into a `Document`.

    A format we cannot parse comes back with ``readable=False`` and an error
    rather than raising, so a single bad attachment never halts a batch run.
    """
    role = role or role_from_path(path)
    extension = os.path.splitext(path)[1].lower()

    if extension == ".txt":
        return Document(path=path, role=role, text=read_text(data))

    if extension == ".pdf":
        try:
            text, images = read_pdf(data)
        except DocumentUnreadable as exc:
            return Document(path=path, role=role, readable=False, error=str(exc))
        return Document(path=path, role=role, text=text, images=images)

    return Document(
        path=path,
        role=role,
        readable=False,
        error=f"unsupported attachment format: {extension or '(none)'}",
    )
