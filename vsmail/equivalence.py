"""Letting the model dispute a mismatch, without letting it clear one.

The comparator decides equality by normalizing both values and comparing
them, which is right for everything it can specify: unit conversion, digit
grouping, case folding. What it cannot do is recognise that two *differently
named* things are the same thing. "MAERSK LINE A/S" against
"A.P. MOLLER - MAERSK" is a defect by string comparison and quite possibly
the same company.

So the model gets one narrow job here, and the direction matters: it may
**raise doubt about a reported defect, never clear one**. A dispute adds a
concern, which sends the case to a human. It cannot turn a MISMATCH into an
OK, because a model that can approve a discrepancy is a model that can
approve the wrong one, silently, in a compliance domain.

This mirrors `vsmail.consensus`: an optional provider capability, absent on
the mock and the remote client, which then report no dispute. That is
accurate rather than a gap — a deterministic comparison has no opinion to
offer about what a name means.
"""
from __future__ import annotations

from vsmail.compare import FieldComparison


def disputable(comparisons: list[FieldComparison]) -> list[FieldComparison]:
    """The defects worth asking about.

    Only fields where both documents actually state something. A blank on
    either side is a `missing_value` escalation and never reaches here, and
    asking whether a value is equivalent to nothing is not a question.
    """
    return [c for c in comparisons if not c.equal and c.si_value and c.bl_value]


async def disputes(provider, comparisons: list[FieldComparison]) -> tuple[str, ...]:
    """Fields the provider reads as plausibly naming the same thing.

    A provider without `judge_equivalence` disputes nothing.
    """
    judge = getattr(provider, "judge_equivalence", None)
    askable = disputable(comparisons)
    if judge is None or not askable:
        return ()
    pairs = [(c.field, c.si_value, c.bl_value) for c in askable]
    disputed = await judge(pairs)
    # Never take a field the comparator did not report, whatever comes back.
    allowed = {c.field for c in askable}
    return tuple(field for field in disputed if field in allowed)


def concerns_for(disputed: tuple[str, ...]) -> list[str]:
    """How a dispute reads in the review queue."""
    if not disputed:
        return []
    fields = ", ".join(disputed)
    return [
        f"the model reads the differing {fields} as possibly the same entity; "
        "reported as a defect anyway"
    ]
