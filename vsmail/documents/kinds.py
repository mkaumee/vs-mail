"""Detecting a document that does not belong in the SI or BL slot.

Five emails in the bundle attach a commercial invoice, packing list or
certificate of origin where the draft BL should be. Those cannot be compared
against a shipping instruction and must be escalated as `wrong_doc_type`
rather than silently producing garbage field values.

Only the disqualifying kinds are detected. Telling a shipping instruction
apart from a bill of lading is deliberately *not* attempted here: two SI
files in this bundle are titled "BILL OF LADING INSTRUCTION", so any such
guess would be wrong. Slot membership comes from the filename instead.
"""
from __future__ import annotations

import re

#: How many lines from the top to search. A document's kind is stated in its
#: heading; the spreadsheet attachments put a company name above it, so the
#: window is a little wider than the first line.
HEAD_LINES = 12

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("commercial_invoice", re.compile(r"\bCOMMERCIAL\s+INVOICE\b", re.I)),
    ("packing_list", re.compile(r"\bPACKING\s+LIST\b", re.I)),
    ("certificate_of_origin", re.compile(r"\bCERTIFICATE\s+OF\s+ORIGIN\b", re.I)),
)

#: Kinds that disqualify a document from being compared.
DISQUALIFYING = frozenset(name for name, _ in _PATTERNS)


def detect_doc_kind(text: str) -> str | None:
    """Name the document's kind when it is one we must reject.

    Returns None for anything that looks like a shipping document, and for a
    scan with no text layer — there is nothing to match against, so the
    decision falls to the extractor.
    """
    if not text.strip():
        return None
    head = "\n".join(text.splitlines()[:HEAD_LINES])
    for name, pattern in _PATTERNS:
        if pattern.search(head):
            return name
    return None
