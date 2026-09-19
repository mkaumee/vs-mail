"""A deterministic stand-in for the model.

This is not only a test fixture. It runs the whole pipeline offline, for
free, and produces a real baseline submission, which gives us something to
measure the model against when we have no ground truth. Tests stay fast and
need no secret.

Classification is by the request verb in the body, as the model's prompt also
instructs. Subjects in this bundle are actively misleading: the same
"TO CONFIRM DOCS" heads both a genuine comparison request and a request to
produce a document. Extraction reuses the label parser in `vsmail.fields`,
which reads the same-line and block layouts but cannot read a scan.
"""
from __future__ import annotations

import re

from vsmail.fields import parse_fields
from vsmail.models import Classification, Document, EmailRecord, Extraction

#: Tried in order; the first pattern that matches the trimmed body wins.
#: Spam is checked first because it borrows freight vocabulary — a fake
#: customs-fee demand mentions packages and delivery.
_RULES: tuple[tuple[str, str], ...] = (
    (
        "SPAM",
        r"click here to claim|monthly draw|limited time offer|buy now before"
        r"|urgent business proposal|unpaid customs fee|you have won"
        r"|exceeded its storage limit|verify your account"
        r"|complete this short survey|bank officer",
    ),
    (
        "BL_COMPARISON",
        r"compare the si and (the )?draft bl"
        r"|check the draft bl against the si"
        r"|attached\s+(are\s+)?(the\s+)?si and (the\s+)?draft bl"
        r"|attached the shipping instruction and the draft bill of lading"
        r"|(check|verify|confirm)[^.]{0,60}\bsi\b[^.]{0,60}\bbl\b"
        r"|\bsi\b[^.]{0,40}(against|versus|vs\.?)[^.]{0,40}\bbl\b"
        # Emails 501-505 attach the wrong second document and say so. They are
        # still comparison requests, and naming the wrong document must not
        # divert them into INVOICE_QUERY.
        r"|confirm the bl is in order"
        r"|find attached the si and\b",
    ),
    (
        "SI_REQUEST",
        r"assist to send the draft bl|send (us|me) the draft bl"
        r"|please find shipping instruction",
    ),
    (
        "GENERAL",
        r"this is an automated notification|berthing report"
        r"|list of outstanding bl|outstanding list|update summary"
        r"|happy and prosperous|office resumes normal operations"
        r"|please submit si & aed",
    ),
    (
        "INVOICE_QUERY",
        r"\binvoice\b|\bthc\b|local charge|d&d|detention charge"
        r"|debit note|credit note|confirm the amount before we release",
    ),
)

_COMPILED = tuple((category, re.compile(pattern, re.I)) for category, pattern in _RULES)


def classify_text(body: str, has_si_and_bl: bool = False) -> Classification:
    """Categorise one email body. Shared so tests can call it directly."""
    for category, pattern in _COMPILED:
        if pattern.search(body):
            return Classification(category=category, rationale=pattern.pattern[:40])
    if has_si_and_bl:
        # Both documents attached and nothing else matched: treat the
        # attachments as the request.
        return Classification(
            category="BL_COMPARISON", confidence=0.6, rationale="SI and BL attached"
        )
    return Classification(category="GENERAL", confidence=0.5, rationale="no rule matched")


class MockProvider:
    """Rule-based provider. No network, no key, fully deterministic."""

    name = "mock"

    async def classify(self, email: EmailRecord) -> Classification:
        has_pair = bool(email.attachment_for("SI") and email.attachment_for("BL"))
        return classify_text(email.core_body, has_si_and_bl=has_pair)

    async def extract(self, si: Document, bl: Document) -> Extraction:
        return Extraction(si=parse_fields(si.text), bl=parse_fields(bl.text))

    async def aclose(self) -> None:
        return None
