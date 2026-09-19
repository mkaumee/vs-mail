"""Running one email, and running all of them.

Extraction is attempted only once an email has survived the cheaper checks,
so a missing, unreadable or wrong document never costs a model call.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from vsmail.compare import decide
from vsmail.config import CONFIDENCE_THRESHOLD, CONSENSUS_MODE
from vsmail.consensus import extract_with_consensus
from vsmail.documents import read_document
from vsmail.documents.kinds import DISQUALIFYING
from vsmail.inbox import Bundle
from vsmail.llm.base import Provider
from vsmail.models import Document, EmailRecord, Extraction, Verdict

#: Concurrent in-flight emails. High enough to keep a 520-email run brisk,
#: low enough not to trip provider rate limits.
DEFAULT_CONCURRENCY = 12


@dataclass
class Processed:
    """A verdict together with the evidence behind it.

    The submission needs only the verdict, but the values the provider read
    are what make a decision auditable — most of all for a scan, where there
    is no second opinion to check against.
    """

    verdict: Verdict
    extraction: Extraction | None = None
    si: Document | None = None
    bl: Document | None = None
    #: What the provider reported for its own classification.
    confidence: float = 1.0
    #: Why this case wants a human, beyond anything the submission records.
    #: Never changes the submission — it feeds the review queue.
    concerns: tuple[str, ...] = ()


def _load(bundle: Bundle, email: EmailRecord, role: str) -> Document | None:
    path = email.attachment_for(role)
    if path is None:
        return None
    try:
        return read_document(path, bundle.read_bytes(path))
    except Exception as exc:  # the attachment is referenced but unfetchable
        return Document(path=path, role=role, readable=False, error=str(exc))


async def process_email(
    bundle: Bundle, provider: Provider, email: EmailRecord
) -> Processed:
    """Classify one email and, if it is a comparison request, decide it."""
    classification = await provider.classify(email)
    category = classification.category

    concerns: list[str] = []
    if classification.confidence < CONFIDENCE_THRESHOLD:
        # The model is unsure which category this is. Its best guess still
        # goes in the submission — every email needs one of the five and the
        # schema cannot express doubt — but the case is flagged for review.
        concerns.append(
            f"classified {category} with confidence {classification.confidence:.2f}"
        )

    if category != "BL_COMPARISON":
        return Processed(
            Verdict(email_id=email.email_id, category=category),
            confidence=classification.confidence,
            concerns=tuple(concerns),
        )

    si = _load(bundle, email, "SI")
    bl = _load(bundle, email, "BL")

    blocked = (
        si is None
        or bl is None
        or not si.readable
        or not bl.readable
        or si.doc_kind in DISQUALIFYING
        or bl.doc_kind in DISQUALIFYING
    )
    extraction = None if blocked else await extract_with_consensus(provider, si, bl)

    if extraction is not None and extraction.uncertain_fields:
        fields = ", ".join(extraction.uncertain_fields)
        concerns.append(f"two readings disagreed on {fields}")
        if CONSENSUS_MODE == "blocking":
            # Escalating costs a caught defect whenever the verdict was right,
            # and defects are half the score — so this is opt-in and measured
            # rather than assumed to help.
            return Processed(
                verdict=Verdict(
                    email_id=email.email_id,
                    category=category,
                    status="NEEDS_REVIEW",
                    review_reason="missing_value",
                ),
                extraction=extraction,
                si=si,
                bl=bl,
                confidence=classification.confidence,
                concerns=tuple(concerns),
            )

    return Processed(
        verdict=decide(email, category, si, bl, extraction),
        extraction=extraction,
        si=si,
        bl=bl,
        confidence=classification.confidence,
        concerns=tuple(concerns),
    )


async def process_all(
    bundle: Bundle,
    provider: Provider,
    concurrency: int = DEFAULT_CONCURRENCY,
    emails: list[EmailRecord] | None = None,
) -> list[Processed]:
    """Process the inbox, preserving email order in the result.

    `emails` narrows the run to a subset, which is how a paid provider gets
    smoke-tested on a handful of emails before spending a full pass.
    """
    emails = bundle.emails() if emails is None else emails
    limit = asyncio.Semaphore(concurrency)

    failures: list[tuple[str, str]] = []

    async def one(email: EmailRecord) -> Processed:
        async with limit:
            try:
                return await process_email(bundle, provider, email)
            except Exception as exc:
                # The email still needs an entry — all 520 must be present —
                # and it is escalated rather than quietly defaulted to OK, so
                # a processing failure stays visible instead of scoring as a
                # confident wrong answer.
                failures.append((email.email_id, f"{type(exc).__name__}: {exc}"))
                return Processed(
                    Verdict(
                        email_id=email.email_id,
                        category="BL_COMPARISON",
                        status="NEEDS_REVIEW",
                        review_reason="unreadable",
                    )
                )

    results = list(await asyncio.gather(*(one(email) for email in emails)))
    if failures:
        print(f"  {len(failures)} email(s) failed and were escalated for review:")
        for email_id, message in failures[:5]:
            print(f"    {email_id}: {message}")
    return results


async def run(
    bundle: Bundle,
    provider: Provider,
    concurrency: int = DEFAULT_CONCURRENCY,
    emails: list[EmailRecord] | None = None,
) -> list[Verdict]:
    """Process the inbox and return verdicts alone.

    Use `process_all` when the evidence behind each verdict is wanted too.
    """
    processed = await process_all(bundle, provider, concurrency, emails)
    return [item.verdict for item in processed]
