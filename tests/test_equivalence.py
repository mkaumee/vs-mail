"""The model may dispute a defect. It may not clear one.

The direction is the whole feature, so most of these tests are about what a
dispute cannot do.
"""
import asyncio

import pytest

from vsmail.compare import compare_all, compare_field
from vsmail.equivalence import concerns_for, disputable, disputes
from vsmail.models import Extraction


class Disputing:
    """A provider that calls everything it is shown the same entity."""

    name = "disputing"

    def __init__(self):
        self.asked = []

    async def judge_equivalence(self, pairs):
        self.asked.append(pairs)
        return tuple(field for field, _, _ in pairs)


class Silent:
    """A provider with no opinion — the mock and the remote client."""

    name = "silent"


def run(coro):
    return asyncio.run(coro)


# -- which defects are worth asking about --------------------------------
def test_only_defects_are_disputable():
    comparisons = [
        compare_field("shipper", "MAERSK LINE", "Maersk Line"),        # equal
        compare_field("consignee", "ACME LTD", "ACME PTE LTD"),        # differs
    ]
    assert [c.field for c in disputable(comparisons)] == ["consignee"]


def test_a_blank_side_is_not_disputable():
    """A missing value is a `missing_value` escalation, and asking whether a
    name is equivalent to nothing is not a question."""
    comparisons = [compare_field("consignee", "ACME LTD", None)]
    assert disputable(comparisons) == []


# -- what a provider without the capability does -------------------------
def test_a_provider_with_no_opinion_disputes_nothing():
    """Absence means absence. A deterministic comparison has nothing to say
    about what a company name denotes, and should not pretend otherwise."""
    comparisons = [compare_field("consignee", "ACME LTD", "ACME PTE LTD")]
    assert run(disputes(Silent(), comparisons)) == ()


def test_nothing_is_asked_when_there_are_no_defects():
    provider = Disputing()
    comparisons = [compare_field("shipper", "MAERSK LINE", "Maersk Line")]
    assert run(disputes(provider, comparisons)) == ()
    assert provider.asked == []


# -- the guard on what comes back ----------------------------------------
def test_a_field_the_comparator_did_not_report_is_ignored():
    """The model answers with field names, and a name it invents — or one for
    a field that compared equal — must not become a concern."""

    class Inventive:
        name = "inventive"

        async def judge_equivalence(self, pairs):
            return ("shipper", "not_a_field", "consignee")

    comparisons = [
        compare_field("shipper", "MAERSK LINE", "Maersk Line"),    # equal
        compare_field("consignee", "ACME LTD", "ACME PTE LTD"),    # differs
    ]
    assert run(disputes(Inventive(), comparisons)) == ("consignee",)


def test_the_pairs_carry_the_written_values():
    provider = Disputing()
    comparisons = [compare_field("consignee", "ACME LTD", "ACME PTE LTD")]
    run(disputes(provider, comparisons))
    assert provider.asked == [[("consignee", "ACME LTD", "ACME PTE LTD")]]


# -- how it reads ---------------------------------------------------------
def test_a_dispute_says_the_defect_still_stands():
    concern = concerns_for(("consignee",))[0]
    assert "consignee" in concern
    assert "reported as a defect anyway" in concern


def test_no_dispute_is_no_concern():
    assert concerns_for(()) == []


# -- the pipeline: a dispute flags, it never clears -----------------------
def _extraction_with_a_defect() -> Extraction:
    values = {
        "shipper": "KPP ANTALIS",
        "consignee": "ACME LTD",
        "notify_party": "ACME LTD",
        "port_of_loading": "SINGAPORE",
        "port_of_discharge": "NHAVA SHEVA",
        "container_count": "6",
        "gross_weight_kg": "22000 KG",
    }
    return Extraction(si=dict(values), bl=dict(values) | {"consignee": "ACME PTE LTD"})


def test_a_dispute_flags_the_case_without_changing_the_verdict(monkeypatch):
    """Advisory is the default, and this is the test that pins it.

    Escalating on the model's doubt was measured once before, on extraction
    consensus, and it cost three correct mismatches. The submission keeps the
    defect; the human gets told there is an argument about it.
    """
    from vsmail import pipeline
    from vsmail.inbox import Bundle
    from vsmail.models import Classification

    extraction = _extraction_with_a_defect()

    class Provider(Disputing):
        async def classify(self, email):
            return Classification(category="BL_COMPARISON", confidence=1.0)

        async def extract(self, si, bl):
            return extraction

    bundle = Bundle()
    email = bundle.get("email_004")
    processed = asyncio.run(pipeline.process_email(bundle, Provider(), email))

    assert processed.verdict.status == "MISMATCH"
    assert processed.verdict.defect_fields == ["consignee"]
    assert processed.verdict.has_defect is True
    assert any("same entity" in c for c in processed.concerns)


def test_the_comparator_still_decides_what_a_defect_is():
    """The judge never sees a field the comparator accepted, so it cannot
    reopen one."""
    extraction = _extraction_with_a_defect()
    defects = [c.field for c in compare_all(extraction) if not c.equal]
    assert defects == ["consignee"]


def test_blocking_mode_escalates_instead(monkeypatch):
    """The flag exists so the trade can be measured, not because it is on.

    It was measured once already for extraction consensus and lost three real
    defects, so this proves the switch works and nothing more.
    """
    from vsmail import pipeline
    from vsmail.inbox import Bundle
    from vsmail.models import Classification

    monkeypatch.setattr(pipeline, "EQUIVALENCE_MODE", "blocking")
    extraction = _extraction_with_a_defect()

    class Provider(Disputing):
        async def classify(self, email):
            return Classification(category="BL_COMPARISON", confidence=1.0)

        async def extract(self, si, bl):
            return extraction

    bundle = Bundle()
    processed = asyncio.run(
        pipeline.process_email(bundle, Provider(), bundle.get("email_004"))
    )
    assert processed.verdict.status == "NEEDS_REVIEW"
    assert processed.verdict.has_defect is False
