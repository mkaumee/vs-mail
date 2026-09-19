"""What a run recorded, as the app reads it back."""
import asyncio

import pytest

from vsmail import pipeline
from vsmail.llm.mock import MockProvider
from vsmail.results import PRIORITY, ResultStore, summarize


@pytest.fixture(scope="module")
def processed(bundle):
    return asyncio.run(pipeline.process_all(bundle, MockProvider()))


@pytest.fixture
def store(tmp_path, processed, bundle):
    store = ResultStore(tmp_path / "results.json")
    store.record(processed, {e.email_id: e for e in bundle.emails()}, "bundle")
    return store


def test_comparison_requests_come_first():
    """Sorting one long list by arrival buries the actual work."""
    assert PRIORITY["BL_COMPARISON"] == 0
    assert PRIORITY["SPAM"] == max(PRIORITY.values())


def test_every_email_is_recorded(store):
    assert len(store.results) == 520


def test_a_result_carries_what_the_app_shows(store):
    result = store.results["email_004"]
    assert result.subject and result.sender
    assert result.defect_fields == ["consignee", "notify_party"]
    assert len(result.fields) == 7


def test_the_field_detail_explains_an_accepted_difference(store):
    """email_516's ports are written differently and still match; the app has
    to be able to say why, or a reviewer sees an unexplained discrepancy."""
    ports = [
        f for f in store.results["email_516"].fields if f["field"] == "port_of_loading"
    ][0]
    assert ports["equal"]
    assert ports["si"] != ports["bl"]
    assert "code ignored" in ports["note"]


def test_lanes_put_problems_at_the_top(store):
    lane = store.lanes()["BL_COMPARISON"]
    mismatches = sum(1 for r in lane if r.status == "MISMATCH")
    assert all(r.status == "MISMATCH" for r in lane[:mismatches])


def test_stats_summarise_the_run(store):
    stats = store.stats()
    assert stats["total"] == 520
    assert stats["defects_found"] == 46
    assert stats["by_category"]["BL_COMPARISON"] == 129
    assert stats["source"] == "bundle"
    assert stats["minutes_saved"] > 0


def test_results_survive_a_reload(store, tmp_path):
    again = ResultStore(tmp_path / "results.json")
    assert len(again.results) == 520
    assert again.results["email_004"].defect_fields == ["consignee", "notify_party"]


def test_an_escalated_email_is_marked_as_needing_a_person(store):
    assert store.results["email_501"].needs_person
    assert not store.results["email_009"].needs_person


def test_summarize_handles_an_email_with_no_documents(processed):
    spam = next(p for p in processed if p.verdict.category == "SPAM")
    result = summarize(spam, None)
    assert result.fields == []
    assert result.si_source is None
