"""Deciding whether a draft BL matches its shipping instruction.

The model extracts; this module decides. Equality is never asked of the
model, because a model asked "do these match?" will sometimes flag
"MAERSK LINE" against "Maersk Line", and a false alarm costs as much as a
missed defect.

When the comparison cannot be trusted the email is escalated instead, with
the reason recorded, rather than guessed at or failed silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from vsmail.config import FIELDS
from vsmail.documents.kinds import DISQUALIFYING
from vsmail.models import Document, EmailRecord, Extraction, Verdict
from vsmail.normalize import (
    normalize_container_count,
    normalize_name,
    normalize_port,
    normalize_weight_kg,
    port_code,
)

_PARTY_FIELDS = ("shipper", "consignee", "notify_party")
_PORT_FIELDS = ("port_of_loading", "port_of_discharge")


@dataclass(frozen=True)
class FieldComparison:
    """One field, as each document states it and as we read it."""

    field: str
    si_value: str | None
    bl_value: str | None
    equal: bool
    note: str | None = None

    @property
    def differs_on_paper(self) -> bool:
        """True when the written values differ, whatever the verdict."""
        return (self.si_value or "") != (self.bl_value or "")


def normalized_for(field: str, value: str | None):
    """The comparable form of a value, by field. Shared with consensus."""
    if field in _PARTY_FIELDS:
        return normalize_name(value)
    if field in _PORT_FIELDS:
        return normalize_port(value)
    if field == "container_count":
        return normalize_container_count(value)
    return normalize_weight_kg(value)


def _explain(field: str, si_value: str, bl_value: str) -> str:
    """Say why two differently written values were treated as equal.

    Proving the absence of a false alarm is otherwise invisible: nobody
    notices a defect that was correctly not raised.
    """
    if field == "gross_weight_kg":
        digits = [re.sub(r"\D", "", value) for value in (si_value, bl_value)]
        if digits[0] == digits[1]:
            return "digit grouping and unit spelling ignored"
        return "unit converted to kilograms"
    if field in _PORT_FIELDS:
        if port_code(si_value) != port_code(bl_value):
            return "port name matches; code ignored"
        return "port code formatting ignored"
    if field == "container_count":
        return "container type ignored; count matches"
    return "case and punctuation normalized"


def compare_field(field: str, si_value: str | None, bl_value: str | None) -> FieldComparison:
    """Compare one field's value across the two documents."""
    si_normalized = normalized_for(field, si_value)
    bl_normalized = normalized_for(field, bl_value)
    equal = si_normalized == bl_normalized

    note = None
    if equal and si_value and bl_value and si_value != bl_value:
        note = _explain(field, si_value, bl_value)
    return FieldComparison(field, si_value, bl_value, equal, note)


def compare_all(extraction: Extraction) -> list[FieldComparison]:
    """Compare all seven fields, in report order."""
    return [
        compare_field(field, extraction.si.get(field), extraction.bl.get(field))
        for field in FIELDS
    ]


def _review(email_id: str, reason: str) -> Verdict:
    return Verdict(
        email_id=email_id,
        category="BL_COMPARISON",
        status="NEEDS_REVIEW",
        review_reason=reason,
    )


def decide(
    email: EmailRecord,
    category: str,
    si: Document | None,
    bl: Document | None,
    extraction: Extraction | None,
) -> Verdict:
    """Turn a classified email and its documents into a submission verdict.

    The checks run in order of how fundamental the problem is, so the reason
    reported is the first thing that actually went wrong: a document that
    never arrived is reported as missing rather than as an unreadable one,
    and a wrong document is reported as wrong rather than as missing values.
    """
    if category != "BL_COMPARISON":
        return Verdict(email_id=email.email_id, category=category)

    if si is None or bl is None:
        return _review(email.email_id, "missing_attachment")

    if not si.readable or not bl.readable:
        return _review(email.email_id, "unreadable")

    if si.doc_kind in DISQUALIFYING or bl.doc_kind in DISQUALIFYING:
        return _review(email.email_id, "wrong_doc_type")

    if extraction is None or extraction.missing(FIELDS):
        return _review(email.email_id, "missing_value")

    defects = [c.field for c in compare_all(extraction) if not c.equal]
    if defects:
        return Verdict(
            email_id=email.email_id,
            category=category,
            status="MISMATCH",
            has_defect=True,
            defect_fields=defects,
        )
    return Verdict(email_id=email.email_id, category=category)
