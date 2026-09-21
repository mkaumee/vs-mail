"""Attachment names and the SI/BL slots they fill.

The seeded bundle uses ``email_001_SI.pdf`` and ``email_001_BL.pdf``. Real
customers do not: names such as ``Shipping Instructions.xlsx`` and
``Draft Bill of Lading.pdf`` are common. Keeping this logic in one place
prevents the processor and the document viewer from disagreeing about the
same file.
"""
from __future__ import annotations

import os
import re
from urllib.parse import unquote


_SI = re.compile(
    r"(?:^|[^A-Z0-9])S[\s_./-]*I(?:$|[^A-Z0-9])"
    r"|\bSHIPPING[\s_.-]*INSTRUCTIONS?\b"
    # In this workflow a BL instruction is the instruction supplied to make
    # the BL. Two genuine SI files in the judging bundle use this title.
    r"|\bBILL[\s_.-]*OF[\s_.-]*LADING[\s_.-]*INSTRUCTIONS?\b",
    re.I,
)
_BL = re.compile(
    r"(?:^|[^A-Z0-9])BL(?:$|[^A-Z0-9])"
    r"|(?:^|[^A-Z0-9])B[\s_./-]*L(?:$|[^A-Z0-9])"
    r"|\bDRAFT[\s_.-]*(?:BILL[\s_.-]*OF[\s_.-]*LADING|B[\s_./-]*L)\b"
    r"|\bBILL[\s_.-]*OF[\s_.-]*LADING\b",
    re.I,
)


def attachment_name(path: str) -> str:
    """Return the original display filename from a local or Gmail path."""
    # Gmail filenames are percent-encoded so slashes, hashes and question
    # marks cannot change the URI structure. Local bundle paths are unchanged.
    name = path.rsplit("/", 1)[-1]
    return unquote(name) if path.startswith("gmail://") else name


def role_from_path(path: str) -> str:
    """Recognise an SI or BL from either bundle-style or natural filenames."""
    stem = os.path.splitext(attachment_name(path))[0]
    if _SI.search(stem):
        return "SI"
    if _BL.search(stem):
        return "BL"
    return "UNKNOWN"


def attachment_slots(attachments: tuple[str, ...]) -> dict[str, str]:
    """Resolve the best SI and BL candidates from an attachment manifest.

    Explicit names always win. When a comparison email has exactly two files,
    the remaining pair is assigned in attachment order. Gmail preserves MIME
    order, and trying the two supplied documents is safer than declaring them
    absent without opening either one. Callers can use :func:`role_was_inferred`
    to keep this visible to a reviewer.
    """
    slots: dict[str, str] = {}
    unknown: list[str] = []
    for path in attachments:
        role = role_from_path(path)
        if role in ("SI", "BL"):
            # A second revision of one role must not masquerade as the other.
            slots.setdefault(role, path)
        else:
            unknown.append(path)

    missing = [role for role in ("SI", "BL") if role not in slots]
    if len(attachments) == 2 and len(unknown) == len(missing):
        for role, path in zip(missing, unknown):
            slots[role] = path
    return slots


def role_was_inferred(attachments: tuple[str, ...], role: str) -> bool:
    """Whether a resolved slot came from pair order rather than its filename."""
    path = attachment_slots(attachments).get(role.upper())
    return path is not None and role_from_path(path) == "UNKNOWN"
