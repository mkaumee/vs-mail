"""Plain-text attachments — 192 of the bundle's files."""
from __future__ import annotations


def read_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")
