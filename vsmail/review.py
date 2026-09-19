"""The queue of cases a person has to settle, and what they decide.

The system already knows what it cannot decide. This is where that goes.

One rule shapes everything here: **a resolution never edits a verdict.** A
reviewer supplies or corrects an *input* — "the gross weight is 235,550 KG" —
and the comparator runs again over it. Normalization, the escalation
precedence and the defect list all behave exactly as they do for a
machine-read value. One code path decides outcomes, and a correction stays
auditable instead of becoming an override.

Corrections persist, because the pipeline is otherwise stateless and a
decision made today would be lost on tomorrow's run.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vsmail.config import FIELDS
from vsmail.models import Extraction

#: How much a wrong value actually costs, which is not the same for every
#: field. Consignee and notify party carry legal title to the cargo and drive
#: customs clearance; gross weight is a SOLAS VGM declaration, where an error
#: is a vessel-stability problem and a fine. The queue is ordered by this
#: rather than by arrival time.
SEVERITY: dict[str, int] = {
    "consignee": 3,
    "notify_party": 3,
    "gross_weight_kg": 2,
    "shipper": 1,
    "port_of_loading": 1,
    "port_of_discharge": 1,
    "container_count": 1,
}

#: A document that never arrived, will not open, or is the wrong document
#: blocks the whole comparison rather than one field.
REASON_SEVERITY: dict[str, int] = {
    "missing_attachment": 2,
    "unreadable": 2,
    "wrong_doc_type": 2,
}

OPEN = "open"
RESOLVED = "resolved"
AUTO_CLOSED = "auto_closed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Case:
    """One email waiting on a person."""

    email_id: str
    reason: str
    state: str = OPEN
    opened_at: str = field(default_factory=_now)
    #: What the run saw: document sources, the values read, the concerns.
    evidence: dict = field(default_factory=dict)
    #: Values a reviewer supplied or corrected, by side and field.
    corrections: dict = field(default_factory=lambda: {"si": {}, "bl": {}})
    #: An outcome a reviewer forced without supplying values. Recorded
    #: separately because it bypasses the comparator and should be visible.
    settled: dict | None = None
    audit: list = field(default_factory=list)

    @property
    def severity(self) -> int:
        if self.reason in REASON_SEVERITY:
            return REASON_SEVERITY[self.reason]
        fields = self.evidence.get("fields_at_issue") or []
        return max((SEVERITY.get(f, 1) for f in fields), default=1)

    def record(self, action: str, by: str, detail: str) -> None:
        self.audit.append({"at": _now(), "by": by, "action": action, "detail": detail})


def apply_corrections(extraction: Extraction, corrections: dict) -> Extraction:
    """Overlay a reviewer's values onto what the provider read.

    The result goes through the comparator exactly as an uncorrected
    extraction would, so a corrected email reaches its verdict by the normal
    path rather than by having one written for it.
    """
    if not corrections or not (corrections.get("si") or corrections.get("bl")):
        return extraction
    return Extraction(
        si=dict(extraction.si) | dict(corrections.get("si") or {}),
        bl=dict(extraction.bl) | dict(corrections.get("bl") or {}),
        si_snippets=extraction.si_snippets,
        bl_snippets=extraction.bl_snippets,
        uncertain_fields=extraction.uncertain_fields,
    )


def evidence_from(processed) -> dict:
    """The part of a run's result a reviewer needs in order to decide."""

    def source(document) -> str:
        if document is None:
            return "absent"
        if not document.readable:
            return f"unreadable: {document.error}"
        if document.images:
            return f"{len(document.images)} scanned page(s)"
        return f"{len(document.text)} chars of text"

    extraction = processed.extraction
    values: dict[str, dict] = {}
    at_issue: list[str] = []
    if extraction is not None:
        for name in FIELDS:
            si_value, bl_value = extraction.si.get(name), extraction.bl.get(name)
            values[name] = {
                "si": si_value,
                "bl": bl_value,
                "si_snippet": extraction.si_snippets.get(name),
                "bl_snippet": extraction.bl_snippets.get(name),
                "uncertain": name in extraction.uncertain_fields,
            }
            if si_value is None or bl_value is None or name in extraction.uncertain_fields:
                at_issue.append(name)

    return {
        "si": source(processed.si),
        "bl": source(processed.bl),
        "si_path": getattr(processed.si, "path", None),
        "bl_path": getattr(processed.bl, "path", None),
        "category": processed.verdict.category,
        "status": processed.verdict.status,
        "confidence": processed.confidence,
        "concerns": list(processed.concerns),
        "values": values,
        "fields_at_issue": at_issue,
    }


def needs_a_person(processed) -> str | None:
    """Why this email wants a human, or None if it does not.

    Two ways in: the pipeline could not decide, or it decided but the reading
    behind it was not stable.
    """
    if processed.verdict.status == "NEEDS_REVIEW":
        return processed.verdict.review_reason or "unknown"
    if processed.concerns:
        return "uncertain"
    return None


class ReviewStore:
    """Cases on disk.

    A JSON file rather than a database: a few dozen cases over 520 emails do
    not need one, and a file can be read, diffed and shown during a demo.
    """

    def __init__(self, path: str | Path = "review.json"):
        self.path = Path(path)
        self.cases: dict[str, Case] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        raw = json.loads(self.path.read_text())
        self.cases = {
            email_id: Case(**data) for email_id, data in raw.get("cases", {}).items()
        }

    def save(self) -> None:
        payload = {"cases": {k: asdict(v) for k, v in self.cases.items()}}
        self.path.write_text(json.dumps(payload, indent=2) + "\n")

    # -- reading ---------------------------------------------------------
    def get(self, email_id: str) -> Case | None:
        return self.cases.get(email_id)

    def queue(self) -> list[Case]:
        """Open cases, worst first."""
        return sorted(
            (c for c in self.cases.values() if c.state == OPEN),
            key=lambda c: (-c.severity, c.email_id),
        )

    def corrections_for(self, email_id: str) -> dict:
        case = self.cases.get(email_id)
        return case.corrections if case else {}

    def settlement_for(self, email_id: str) -> dict | None:
        case = self.cases.get(email_id)
        return case.settled if case else None

    # -- writing ---------------------------------------------------------
    def sync(self, processed_list) -> dict[str, int]:
        """Open cases for anything a run could not settle on its own.

        A case a person already resolved is left alone — the resolution is
        usually *why* the email no longer needs review, and reopening it would
        undo the work. One that is open but no longer flagged is closed with
        that noted, so the queue does not accumulate stale entries.
        """
        counts = {"opened": 0, "already_open": 0, "auto_closed": 0}
        flagged: set[str] = set()

        for processed in processed_list:
            reason = needs_a_person(processed)
            if reason is None:
                continue
            flagged.add(processed.verdict.email_id)
            existing = self.cases.get(processed.verdict.email_id)
            if existing is None:
                case = Case(
                    email_id=processed.verdict.email_id,
                    reason=reason,
                    evidence=evidence_from(processed),
                )
                case.record("opened", "system", reason)
                self.cases[case.email_id] = case
                counts["opened"] += 1
            elif existing.state == OPEN:
                existing.evidence = evidence_from(processed)
                existing.reason = reason
                counts["already_open"] += 1

        for case in self.cases.values():
            if case.state == OPEN and case.email_id not in flagged:
                case.state = AUTO_CLOSED
                case.record("auto_closed", "system", "no longer flagged by a run")
                counts["auto_closed"] += 1

        self.save()
        return counts

    def resolve(
        self,
        email_id: str,
        by: str,
        *,
        confirm: bool = False,
        si: dict | None = None,
        bl: dict | None = None,
        settle: dict | None = None,
        note: str = "",
    ) -> Case:
        """Record what a person decided.

        `si`/`bl` supply or correct values and are the normal path: the next
        run compares them like any other reading. `settle` forces an outcome
        without values and is recorded distinctly, because it is the one
        action that bypasses the comparator.
        """
        case = self.cases.get(email_id)
        if case is None:
            raise KeyError(f"no case for {email_id}")

        for side, values in (("si", si), ("bl", bl)):
            for name, value in (values or {}).items():
                if name not in FIELDS:
                    raise ValueError(f"{name!r} is not one of the compared fields")
                case.corrections[side][name] = value
                case.record("correct", by, f"{side}.{name} = {value!r}")

        if settle:
            case.settled = settle
            case.record("settle", by, json.dumps(settle, sort_keys=True))
        if confirm:
            case.record("confirm", by, "escalation was correct")
        if note:
            case.record("note", by, note)

        case.state = RESOLVED
        self.save()
        return case
