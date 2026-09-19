"""Running one email, and running all of them.

Extraction is attempted only once an email has survived the cheaper checks,
so a missing, unreadable or wrong document never costs a model call.
"""
from __future__ import annotations

import asyncio

from vsmail.compare import decide
from vsmail.documents import read_document
from vsmail.documents.kinds import DISQUALIFYING
from vsmail.inbox import Bundle
from vsmail.llm.base import Provider
from vsmail.models import Document, EmailRecord, Verdict

#: Concurrent in-flight emails. High enough to keep a 520-email run brisk,
#: low enough not to trip provider rate limits.
DEFAULT_CONCURRENCY = 12


def _load(bundle: Bundle, email: EmailRecord, role: str) -> Document | None:
    path = email.attachment_for(role)
    if path is None:
        return None
    try:
        return read_document(path, bundle.read_bytes(path))
    except Exception as exc:  # the attachment is referenced but unfetchable
        return Document(path=path, role=role, readable=False, error=str(exc))


async def process_email(bundle: Bundle, provider: Provider, email: EmailRecord) -> Verdict:
    """Classify one email and, if it is a comparison request, decide it."""
    classification = await provider.classify(email)
    category = classification.category

    if category != "BL_COMPARISON":
        return Verdict(email_id=email.email_id, category=category)

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
    extraction = None if blocked else await provider.extract(si, bl)
    return decide(email, category, si, bl, extraction)


async def run(
    bundle: Bundle,
    provider: Provider,
    concurrency: int = DEFAULT_CONCURRENCY,
    emails: list[EmailRecord] | None = None,
) -> list[Verdict]:
    """Process the inbox, preserving email order in the result.

    `emails` narrows the run to a subset, which is how a paid provider gets
    smoke-tested on a handful of emails before spending a full pass.
    """
    emails = bundle.emails() if emails is None else emails
    limit = asyncio.Semaphore(concurrency)

    failures: list[tuple[str, str]] = []

    async def one(email: EmailRecord) -> Verdict:
        async with limit:
            try:
                return await process_email(bundle, provider, email)
            except Exception as exc:
                # The email still needs an entry — all 520 must be present —
                # and it is escalated rather than quietly defaulted to OK, so
                # a processing failure stays visible instead of scoring as a
                # confident wrong answer.
                failures.append((email.email_id, f"{type(exc).__name__}: {exc}"))
                return Verdict(
                    email_id=email.email_id,
                    category="BL_COMPARISON",
                    status="NEEDS_REVIEW",
                    review_reason="unreadable",
                )

    verdicts = list(await asyncio.gather(*(one(email) for email in emails)))
    if failures:
        print(f"  {len(failures)} email(s) failed and were escalated for review:")
        for email_id, message in failures[:5]:
            print(f"    {email_id}: {message}")
    return verdicts
