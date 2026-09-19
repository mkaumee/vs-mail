"""Reading each document twice and noticing where the readings differ.

A model that misreads a scanned document confidently produces values that
look entirely reasonable, and nothing downstream can tell. Reading twice and
comparing is the only signal available, because there is no second source to
check against.

Repeating the identical call would not work. The client sends
``temperature: 0``, so a second identical request returns the same JSON: it
would agree with itself, catch nothing, and double the bill. The second pass
therefore changes the *framing* rather than the sampling — it presents the
draft bill of lading first and the shipping instruction second. A field read
differently depending on document order is genuinely unstable, which is
exactly what is worth escalating.
"""
from __future__ import annotations

from vsmail.compare import normalized_for
from vsmail.config import FIELDS
from vsmail.models import Document, Extraction


def disagreements(first: Extraction, second: Extraction) -> tuple[str, ...]:
    """Fields the two passes read differently.

    Values are compared after normalization, so "22,000 KG" against
    "22000 kgs" is agreement — the two passes read the same weight and merely
    wrote it differently, which says nothing about reliability.
    """
    differing = []
    for field in FIELDS:
        for side in ("si", "bl"):
            a = getattr(first, side).get(field)
            b = getattr(second, side).get(field)
            if normalized_for(field, a) != normalized_for(field, b):
                differing.append(field)
                break
    return tuple(differing)


def merge(first: Extraction, second: Extraction) -> Extraction:
    """Keep the first pass's reading, recording where the second differed.

    The first pass is canonical because it sees the documents in their
    natural order; the second exists to disagree, not to overrule.
    """
    return Extraction(
        si=first.si,
        bl=first.bl,
        si_snippets=first.si_snippets,
        bl_snippets=first.bl_snippets,
        uncertain_fields=disagreements(first, second),
    )


async def extract_with_consensus(provider, si: Document, bl: Document) -> Extraction:
    """Extract, using a provider's second pass when it offers one.

    A provider without `extract_twice` — the deterministic mock, or the remote
    client, which gets consensus from the service instead — is called once and
    reports no uncertainty. That is accurate, not a gap: repeating a
    deterministic reading tells you nothing.
    """
    twice = getattr(provider, "extract_twice", None)
    if twice is None:
        return await provider.extract(si, bl)
    return await twice(si, bl)
