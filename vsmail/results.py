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

#: Where an email goes once its reply has actually been sent. A lane, never a
#: category: `category` is what the submission carries, and the schema allows
#: exactly the five above.
READ = "READ"


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
    attachment_count: int = 0
    gmail_message_id: str | None = None
    #: When a reply was actually sent. A saved draft does not count —
    #: nobody has been replied to yet.
    sent_at: str | None = None

    @property
    def priority(self) -> int:
        return PRIORITY.get(self.category, 9)

    @property
    def needs_person(self) -> bool:
        # A clean comparison remains a clean comparison. Advisory notes may
        # still be shown beside it, but they must not suppress its confirmation
        # draft or move it into Help. A disputed mismatch remains worth a look.
        return self.status == "NEEDS_REVIEW" or (
            self.status == "MISMATCH" and bool(self.concerns)
        )


def _source(document) -> str | None:
    if document is None:
        return None
    if not document.readable:
        return "automatic reading failed"
    if document.images:
        return f"{len(document.images)} scanned page(s)"
    return f"{len(document.text)} characters of text"


def summarize(
    processed,
    record: EmailRecord | None = None,
    gmail_message_id: str | None = None,
) -> Result:
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
        attachment_count=len(record.attachments) if record else 0,
        gmail_message_id=gmail_message_id,
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

    def clear(self) -> int:
        """Forget the last run. Returns how many results were dropped.

        Clearing the mailbox used to leave all 520 results on screen, because
        they live here rather than in Gmail, so "clear" visibly did half of
        what it said.
        """
        dropped = len(self.results)
        self.results = {}
        self.ran_at = None
        self.source = None
        self.save()
        return dropped

    def record(
        self,
        processed_list,
        records: dict[str, EmailRecord],
        source: str,
        gmail_message_ids: dict[str, str] | None = None,
    ) -> None:
        for processed in processed_list:
            email_id = processed.verdict.email_id
            existing = self.results.get(email_id)
            result = summarize(
                processed,
                records.get(email_id),
                (gmail_message_ids or {}).get(email_id),
            )
            # A rerun updates the verdict; it does not unsend a reply or lose
            # the Gmail identity needed to load and thread it efficiently.
            if existing:
                result.sent_at = existing.sent_at
                result.gmail_message_id = result.gmail_message_id or existing.gmail_message_id
            self.results[email_id] = result
        self.ran_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.source = source
        self.save()

    def update_one(self, processed, record: EmailRecord | None = None) -> Result:
        """Replace one email's result after it was reprocessed on its own.

        Deliberately does not touch `ran_at` or `source`: those describe the
        run that produced the rest of the table, and a single retry is not a
        new run. Saying otherwise would make the whole inbox look fresher than
        it is.
        """
        existing = self.results.get(processed.verdict.email_id)
        result = summarize(
            processed,
            record,
            existing.gmail_message_id if existing else None,
        )
        if existing:
            result.sent_at = existing.sent_at
        self.results[processed.verdict.email_id] = result
        self.save()
        return result

    def mark_sent(self, email_id: str, when: str | None = None) -> Result | None:
        """Record that a reply actually went out, which moves it to READ."""
        from datetime import datetime, timezone

        result = self.results.get(email_id)
        if result is None:
            return None
        result.sent_at = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save()
        return result

    # -- what the app asks for -------------------------------------------
    def lanes(self) -> dict[str, list[Result]]:
        """Grouped by category, comparison requests first.

        Anything replied to leaves its lane for READ. A queue that still
        holds what you have already answered stops being a queue — you lose
        your place every time the list reorders around work that is done.
        """
        grouped: dict[str, list[Result]] = {name: [] for name in PRIORITY}
        grouped[READ] = []
        for result in self.results.values():
            lane = READ if result.sent_at else result.category
            grouped.setdefault(lane, []).append(result)
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
