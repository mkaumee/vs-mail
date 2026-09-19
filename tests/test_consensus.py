"""Uncertainty: the model's doubt, and two readings that differ."""
import pytest

from vsmail import pipeline
from vsmail.consensus import disagreements, extract_with_consensus, merge
from vsmail.inbox import Bundle
from vsmail.llm.mock import MockProvider
from vsmail.models import Classification, Document, Extraction

_SI = Document("a_SI.txt", "SI", text="si")
_BL = Document("a_BL.txt", "BL", text="bl")


def _extraction(**si_overrides) -> Extraction:
    base = {
        "shipper": "ACME LTD",
        "consignee": "BUYER LTD",
        "notify_party": "BUYER LTD",
        "port_of_loading": "SINGAPORE",
        "port_of_discharge": "KARACHI, PAKISTAN",
        "container_count": "6 x 40'HC",
        "gross_weight_kg": "22,000 KG",
    }
    return Extraction(si=dict(base) | si_overrides, bl=dict(base))


def test_identical_readings_disagree_on_nothing():
    assert disagreements(_extraction(), _extraction()) == ()


def test_a_formatting_difference_is_not_a_disagreement():
    """Two passes writing the same weight differently agree about the weight."""
    a = _extraction(gross_weight_kg="22,000 KG")
    b = _extraction(gross_weight_kg="22000 kgs")
    assert disagreements(a, b) == ()


def test_a_different_value_is_a_disagreement():
    a = _extraction(consignee="BUYER LTD")
    b = _extraction(consignee="SOMEONE ELSE LTD")
    assert disagreements(a, b) == ("consignee",)


def test_a_value_read_by_one_pass_only_is_a_disagreement():
    assert disagreements(_extraction(shipper=None), _extraction()) == ("shipper",)


def test_the_first_pass_is_the_one_kept():
    """The second pass exists to disagree, not to overrule."""
    first = _extraction(consignee="FIRST READING")
    second = _extraction(consignee="SECOND READING")
    merged = merge(first, second)
    assert merged.si["consignee"] == "FIRST READING"
    assert merged.uncertain_fields == ("consignee",)


async def test_a_provider_without_a_second_pass_reports_no_uncertainty():
    """Repeating a deterministic reading tells you nothing, so it is not run."""
    extraction = await extract_with_consensus(MockProvider(), _SI, _BL)
    assert extraction.uncertain_fields == ()


class _Unstable:
    """A provider whose two passes read the consignee differently."""

    name = "unstable"

    def __init__(self, confidence: float = 1.0):
        self.confidence = confidence

    async def classify(self, email):
        return Classification("BL_COMPARISON", confidence=self.confidence)

    async def extract(self, si, bl):
        return _extraction()

    async def extract_twice(self, si, bl):
        return merge(_extraction(), _extraction(consignee="A DIFFERENT NAME"))

    async def aclose(self):
        return None


@pytest.fixture
def unstable_run(bundle, monkeypatch):
    async def _run(mode: str, confidence: float = 1.0):
        monkeypatch.setattr(pipeline, "CONSENSUS_MODE", mode)
        emails = [e for e in bundle.emails() if e.email_id == "email_004"]
        results = await pipeline.process_all(bundle, _Unstable(confidence), emails=emails)
        return results[0]

    return _run


async def test_advisory_mode_flags_without_changing_the_verdict(unstable_run):
    """The default. Escalating a correct MISMATCH would lose a caught defect."""
    item = await unstable_run("advisory")
    assert item.verdict.status == "OK", "the verdict must be untouched"
    assert item.extraction.uncertain_fields == ("consignee",)
    assert any("disagreed on consignee" in c for c in item.concerns)


async def test_blocking_mode_escalates_the_case(unstable_run):
    item = await unstable_run("blocking")
    assert item.verdict.status == "NEEDS_REVIEW"
    assert item.verdict.review_reason == "missing_value"
    assert any("disagreed on consignee" in c for c in item.concerns)


async def test_low_confidence_is_flagged(unstable_run):
    item = await unstable_run("advisory", confidence=0.3)
    assert any("confidence 0.30" in c for c in item.concerns)


async def test_low_confidence_does_not_change_the_submission(unstable_run):
    """Every email needs one of the five categories; the schema cannot say
    "unsure", so the best guess still ships and macro-F1 is untouched."""
    confident = await unstable_run("advisory", confidence=1.0)
    unsure = await unstable_run("advisory", confidence=0.1)
    assert unsure.verdict.to_submission_entry() == confident.verdict.to_submission_entry()
    assert unsure.concerns and not any("confidence" in c for c in confident.concerns)


async def test_the_offline_baseline_is_unchanged_by_any_of_this(bundle):
    """The mock is deterministic, so nothing here may alter its output."""
    from vsmail import submission as sub

    verdicts = await pipeline.run(bundle, MockProvider())
    result = sub.build(verdicts)
    assert result["email_004"]["defect_fields"] == ["consignee", "notify_party"]
    assert sum(1 for e in result.values() if e["status"] == "NEEDS_REVIEW") == 20
