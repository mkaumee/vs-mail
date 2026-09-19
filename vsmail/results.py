"""What a run produced, kept so the app can show it without re-running.

The submission carries only a verdict per email. A person looking at an
inbox needs more: the subject, who sent it, which fields disagreed and what
each document actually said. Recomputing that for every page load would mean
re-reading the mailbox and paying for the model again, so a run writes it
down once.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vsmail.compare import compare_all
from vsmail.models import EmailRecord

#: Comparison requests are the work; everything else is triage. The app puts
#: them in their own lane rather than sorting one long list by arrival.
PRIORITY = {
    "BL_COMPARISON": 0,
    "SI_REQUEST": 1,
    "INVOICE_QUERY": 2,
    "GENERAL": 3,
    "SPAM": 4,
}


@dataclass
class Result:
    """One email as the app needs to show it."""

    email_id: str
    category: str
    status: str
    review_reason: str | None = None
    has_defect: bool = False
    defect_fields: list = field(default_factory=list)
    subject: str = ""
    sender: str = ""
    confidence: float = 1.0
    concerns: list = field(default_factory=list)
    provenance: list = field(default_factory=list)
    #: Per-field detail, only for comparison requests that got that far.
    fields: list = field(default_factory=list)
    si_source: str | None = None
    bl_source: str | None = None
    gmail_message_id: str | None = None

    @property
    def priority(self) -> int:
        return PRIORITY.get(self.category, 9)

    @property
    def needs_person(self) -> bool:
        return self.status == "NEEDS_REVIEW" or bool(self.concerns)


def _source(document) -> str | None:
    if document is None:
        return None
    if not document.readable:
        return f"unreadable: {document.error}"
    if document.images:
        return f"{len(document.images)} scanned page(s)"
    return f"{len(document.text)} characters of text"


def summarize(processed, record: EmailRecord | None = None) -> Result:
    """Flatten one processed email into something a browser can render."""
    verdict = processed.verdict
    fields = []
    if processed.extraction is not None:
        uncertain = set(processed.extraction.uncertain_fields)
        for comparison in compare_all(processed.extraction):
            fields.append(
                {
                    "field": comparison.field,
                    "si": comparison.si_value,
                    "bl": comparison.bl_value,
                    "equal": comparison.equal,
                    "note": comparison.note,
                    "uncertain": comparison.field in uncertain,
                }
            )

    return Result(
        email_id=verdict.email_id,
        category=verdict.category,
        status=verdict.status,
        review_reason=verdict.review_reason,
        has_defect=verdict.has_defect,
        defect_fields=list(verdict.defect_fields),
        subject=record.subject if record else "",
        sender=record.sender if record else "",
        confidence=processed.confidence,
        concerns=list(processed.concerns),
        provenance=list(processed.provenance),
        fields=fields,
        si_source=_source(processed.si),
        bl_source=_source(processed.bl),
    )


class ResultStore:
    """The last run's results, on disk."""

    def __init__(self, path: str | Path = "results.json"):
        self.path = Path(path)
        self.results: dict[str, Result] = {}
        self.ran_at: str | None = None
        self.source: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        raw = json.loads(self.path.read_text())
        self.ran_at = raw.get("ran_at")
        self.source = raw.get("source")
        self.results = {k: Result(**v) for k, v in raw.get("results", {}).items()}

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "ran_at": self.ran_at,
                    "source": self.source,
                    "results": {k: asdict(v) for k, v in self.results.items()},
                },
                indent=2,
            )
            + "\n"
        )

    def record(self, processed_list, records: dict[str, EmailRecord], source: str) -> None:
        for processed in processed_list:
            email_id = processed.verdict.email_id
            self.results[email_id] = summarize(processed, records.get(email_id))
        self.ran_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.source = source
        self.save()

    # -- what the app asks for -------------------------------------------
    def lanes(self) -> dict[str, list[Result]]:
        """Grouped by category, comparison requests first."""
        grouped: dict[str, list[Result]] = {name: [] for name in PRIORITY}
        for result in self.results.values():
            grouped.setdefault(result.category, []).append(result)
        for items in grouped.values():
            # Within a lane, anything wrong or uncertain rises to the top.
            items.sort(
                key=lambda r: (
                    0 if r.status == "MISMATCH" else 1 if r.needs_person else 2,
                    r.email_id,
                )
            )
        return grouped

    def stats(self) -> dict:
        results = list(self.results.values())
        defects = sum(1 for r in results if r.status == "MISMATCH")
        review = sum(1 for r in results if r.needs_person)
        return {
            "ran_at": self.ran_at,
            "source": self.source,
            "total": len(results),
            "by_category": {
                name: sum(1 for r in results if r.category == name) for name in PRIORITY
            },
            "defects_found": defects,
            "awaiting_review": review,
            "clean": sum(
                1
                for r in results
                if r.category == "BL_COMPARISON" and r.status == "OK"
            ),
            # A checker doing this by hand spends a few minutes per document
            # pair; five is a conservative estimate for seven fields across
            # two documents in different layouts.
            "minutes_saved": sum(
                5 for r in results if r.category == "BL_COMPARISON"
            ),
        }
