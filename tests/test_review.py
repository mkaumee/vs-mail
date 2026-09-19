"""The review loop: cases, corrections, and the audit trail."""
import asyncio

import pytest

from vsmail import pipeline
from vsmail.llm.mock import MockProvider
from vsmail.models import Extraction
from vsmail.review import (
    AUTO_CLOSED,
    OPEN,
    RESOLVED,
    Case,
    ReviewStore,
    apply_corrections,
)


@pytest.fixture
def store(tmp_path):
    return ReviewStore(tmp_path / "review.json")


@pytest.fixture(scope="module")
def processed(bundle):
    return asyncio.run(pipeline.process_all(bundle, MockProvider()))


def test_corrections_overlay_without_mutating_the_original():
    original = Extraction(si={"gross_weight_kg": None}, bl={"gross_weight_kg": "1 KG"})
    fixed = apply_corrections(original, {"si": {"gross_weight_kg": "1 KG"}, "bl": {}})
    assert fixed.si["gross_weight_kg"] == "1 KG"
    assert original.si["gross_weight_kg"] is None, "the provider's reading is preserved"


def test_no_corrections_returns_the_same_extraction():
    original = Extraction(si={"shipper": "A"}, bl={"shipper": "A"})
    assert apply_corrections(original, {}) is original


def test_severity_reflects_what_a_wrong_value_costs():
    """Consignee carries legal title; a container count does not."""
    critical = Case("e", "missing_value", evidence={"fields_at_issue": ["consignee"]})
    medium = Case("e", "missing_value", evidence={"fields_at_issue": ["container_count"]})
    assert critical.severity > medium.severity


def test_a_blocked_comparison_outranks_a_single_field():
    blocked = Case("e", "unreadable")
    single = Case("e", "missing_value", evidence={"fields_at_issue": ["container_count"]})
    assert blocked.severity > single.severity


def test_a_run_opens_a_case_for_everything_it_could_not_settle(store, processed):
    counts = store.sync(processed)
    assert counts["opened"] == 20
    assert len(store.queue()) == 20
    escalated = {p.verdict.email_id for p in processed if p.verdict.status == "NEEDS_REVIEW"}
    assert {c.email_id for c in store.queue()} == escalated


def test_the_queue_is_ordered_worst_first(store, processed):
    store.sync(processed)
    severities = [case.severity for case in store.queue()]
    assert severities == sorted(severities, reverse=True)


def test_resolving_records_who_decided_what(store, processed):
    store.sync(processed)
    case = store.resolve(
        "email_516", by="ops.mitchelle", si={"gross_weight_kg": "235,550 KG"}
    )
    assert case.state == RESOLVED
    entry = next(e for e in case.audit if e["action"] == "correct")
    assert entry["by"] == "ops.mitchelle"
    assert "235,550 KG" in entry["detail"]


def test_a_correction_survives_a_reload(store, processed, tmp_path):
    store.sync(processed)
    store.resolve("email_516", by="me", si={"gross_weight_kg": "235,550 KG"})
    reloaded = ReviewStore(tmp_path / "review.json")
    assert reloaded.corrections_for("email_516")["si"]["gross_weight_kg"] == "235,550 KG"


def test_an_unknown_field_is_refused(store, processed):
    store.sync(processed)
    with pytest.raises(ValueError, match="not one of the compared fields"):
        store.resolve("email_516", by="me", si={"vessel_name": "X"})


def test_resolving_an_unknown_case_fails(store):
    with pytest.raises(KeyError):
        store.resolve("email_999", by="me", confirm=True)


async def test_a_supplied_value_reaches_its_verdict_through_the_comparator(
    bundle, store, processed
):
    """The point of the whole design: a reviewer supplies an input, and the
    ordinary comparison runs over it. No verdict is written by hand."""
    store.sync(processed)
    before = next(p for p in processed if p.verdict.email_id == "email_516")
    assert before.verdict.status == "NEEDS_REVIEW"
    assert before.verdict.review_reason == "missing_value"

    store.resolve("email_516", by="ops", si={"gross_weight_kg": "235,550 KG"})

    emails = [e for e in bundle.emails() if e.email_id == "email_516"]
    after = (await pipeline.process_all(bundle, MockProvider(), emails=emails, store=store))[0]
    assert after.verdict.status == "OK"
    assert after.verdict.review_reason is None
    assert any("corrected by a reviewer" in c for c in after.concerns)


async def test_a_wrong_supplied_value_produces_a_mismatch(bundle, store, processed):
    """The comparator is genuinely running, not rubber-stamping the reviewer."""
    store.sync(processed)
    store.resolve("email_516", by="ops", si={"gross_weight_kg": "999,999 KG"})
    emails = [e for e in bundle.emails() if e.email_id == "email_516"]
    after = (await pipeline.process_all(bundle, MockProvider(), emails=emails, store=store))[0]
    assert after.verdict.status == "MISMATCH"
    assert after.verdict.defect_fields == ["gross_weight_kg"]


async def test_a_forced_outcome_is_marked_as_not_compared(bundle, store, processed):
    store.sync(processed)
    store.resolve(
        "email_511", by="ops", settle={"status": "OK", "defect_fields": []}
    )
    emails = [e for e in bundle.emails() if e.email_id == "email_511"]
    after = (await pipeline.process_all(bundle, MockProvider(), emails=emails, store=store))[0]
    assert after.verdict.status == "OK"
    assert any("not compared" in c for c in after.concerns)


def test_a_resolved_case_is_not_reopened(store, processed):
    store.sync(processed)
    store.resolve("email_516", by="me", confirm=True)
    store.sync(processed)
    assert store.get("email_516").state == RESOLVED


def test_a_case_no_longer_flagged_is_closed(store, processed):
    store.sync(processed)
    assert store.get("email_516").state == OPEN
    store.sync([p for p in processed if p.verdict.email_id != "email_516"])
    assert store.get("email_516").state == AUTO_CLOSED
