"""Running one email, and running all of them.

Extraction is attempted only once an email has survived the cheaper checks,
so a missing, unreadable or wrong document never costs a model call.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from vsmail.attachments import role_was_inferred
from vsmail.compare import compare_all, decide
from vsmail.config import CONFIDENCE_THRESHOLD, CONSENSUS_MODE, EQUIVALENCE_MODE
from vsmail.consensus import extract_with_consensus
from vsmail.documents import read_document
from vsmail.documents.kinds import DISQUALIFYING
from vsmail.equivalence import concerns_for, disputes
from vsmail.gmail.retry import GmailTemporarilyBusy
from vsmail.inbox import Bundle
from vsmail.llm.base import Provider
from vsmail.models import Document, EmailRecord, Extraction, Verdict
from vsmail.review import apply_corrections

#: Concurrent in-flight emails. High enough to keep a 520-email run brisk,
#: low enough not to trip provider rate limits.
DEFAULT_CONCURRENCY = 12

StageCallback = Callable[[EmailRecord, str], None]


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
    #: Where the values came from. Recorded and displayed, but *not* a reason
    #: to escalate: "a reviewer corrected this" is history, not doubt, and
    #: treating it as doubt would reopen a corrected case forever.
    provenance: tuple[str, ...] = ()


def _load(bundle: Bundle, email: EmailRecord, role: str) -> Document | None:
    path = email.attachment_for(role)
    if path is None:
        return None
    try:
        return read_document(path, bundle.read_bytes(path))
    except GmailTemporarilyBusy:
        raise
    except Exception as exc:  # the attachment is referenced but unfetchable
        return Document(path=path, role=role, readable=False, error=str(exc))


async def process_email(
    bundle: Bundle,
    provider: Provider,
    email: EmailRecord,
    store=None,
    stage: StageCallback | None = None,
) -> Processed:
    """Classify one email and, if it is a comparison request, decide it.

    `store` supplies any values a reviewer has already corrected. They are
    overlaid on what the provider read and then compared normally, so a
    resolved email reaches its verdict through the same path as any other.
    """
    def report(name: str) -> None:
        if stage is not None:
            stage(email, name)

    report("classifying")
    classification = await provider.classify(email)
    category = classification.category

    concerns: list[str] = []
    provenance: list[str] = []
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

    report("reading_documents")
    inferred_roles = [
        role
        for role in ("SI", "BL")
        if role_was_inferred(email.attachments, role)
    ]
    if inferred_roles:
        concerns.append(
            "document role inferred from attachment order: "
            + ", ".join(inferred_roles)
        )
    # A Gmail attachment is a synchronous API call. Running both reads in
    # worker threads keeps the event loop free, so the browser can continue
    # polling the job instead of appearing frozen while documents download.
    si, bl = await asyncio.gather(
        asyncio.to_thread(_load, bundle, email, "SI"),
        asyncio.to_thread(_load, bundle, email, "BL"),
    )

    blocked = (
        si is None
        or bl is None
        or not si.readable
        or not bl.readable
        or si.doc_kind in DISQUALIFYING
        or bl.doc_kind in DISQUALIFYING
    )
    if blocked:
        extraction = None
    else:
        report("extracting")
        extraction = await extract_with_consensus(provider, si, bl)

    corrections = store.corrections_for(email.email_id) if store else {}
    if extraction is not None and corrections:
        extraction = apply_corrections(extraction, corrections)
        provenance.append("includes values corrected by a reviewer")

    settled = store.settlement_for(email.email_id) if store else None
    if settled:
        # The one path that does not run the comparator. Recorded as such so
        # a forced outcome is never mistaken for a computed one.
        provenance.append("outcome set by a reviewer, not compared")
        return Processed(
            verdict=Verdict(
                email_id=email.email_id,
                category=category,
                status=settled.get("status", "OK"),
                review_reason=settled.get("review_reason"),
                has_defect=bool(settled.get("defect_fields")),
                defect_fields=list(settled.get("defect_fields") or []),
            ),
            extraction=extraction,
            si=si,
            bl=bl,
            confidence=classification.confidence,
            concerns=tuple(concerns),
            provenance=tuple(provenance),
        )

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
                provenance=tuple(provenance),
            )

    report("comparing")
    verdict = decide(email, category, si, bl, extraction)

    if verdict.status == "MISMATCH" and extraction is not None:
        # The model may dispute a reported defect, and only in that direction.
        # A dispute adds a concern, which routes the case to a person; it
        # cannot clear the defect. A model able to approve a discrepancy is a
        # model able to approve the wrong one, quietly.
        report("checking_discrepancies")
        disputed = await disputes(provider, compare_all(extraction))
        concerns.extend(concerns_for(disputed))
        if disputed and EQUIVALENCE_MODE == "blocking":
            # Here to be measured, not assumed. The same trade cost three real
            # defects when consensus was allowed to escalate, so this stays off
            # until a run says otherwise.
            verdict = Verdict(
                email_id=email.email_id,
                category=category,
                status="NEEDS_REVIEW",
                review_reason="missing_value",
            )

    return Processed(
        verdict=verdict,
        extraction=extraction,
        si=si,
        bl=bl,
        confidence=classification.confidence,
        concerns=tuple(concerns),
        provenance=tuple(provenance),
    )


async def process_all(
    bundle: Bundle,
    provider: Provider,
    concurrency: int = DEFAULT_CONCURRENCY,
    emails: list[EmailRecord] | None = None,
    store=None,
    progress=None,
    stage: StageCallback | None = None,
) -> list[Processed]:
    """Process the inbox, preserving email order in the result.

    `emails` narrows the run to a subset, which is how a paid provider gets
    smoke-tested on a handful of emails before spending a full pass.
    `progress(done, total)` is called as each finishes, so a browser watching
    a two-minute run has something to show. `stage(email, phase)` reports the
    real work currently happening inside a worker.
    """
    emails = bundle.emails() if emails is None else emails
    limit = asyncio.Semaphore(concurrency)

    failures: list[tuple[str, str]] = []
    finished = 0
    total = len(emails)

    def tick() -> None:
        nonlocal finished
        finished += 1
        if progress is not None:
            progress(finished, total)

    async def one(email: EmailRecord) -> Processed:
        async with limit:
            try:
                return await process_email(
                    bundle, provider, email, store=store, stage=stage
                )
            except GmailTemporarilyBusy:
                # This is a mailbox-wide condition, not a bad email. Let the
                # job fail with a useful retry message instead of recording a
                # false NEEDS_REVIEW verdict for every item.
                raise
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
            finally:
                tick()

    tasks = [asyncio.create_task(one(email)) for email in emails]
    try:
        results = list(await asyncio.gather(*tasks))
    except Exception:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
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
    store=None,
) -> list[Verdict]:
    """Process the inbox and return verdicts alone.

    Use `process_all` when the evidence behind each verdict is wanted too.
    """
    processed = await process_all(bundle, provider, concurrency, emails, store)
    return [item.verdict for item in processed]
