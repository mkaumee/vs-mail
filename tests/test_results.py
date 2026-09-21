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


def test_clearing_forgets_the_run(store):
    """Clearing the mailbox used to leave all 520 results on screen, because
    they live here rather than in Gmail — so "clear" did half of what it said."""
    assert len(store.results) == 520

    dropped = store.clear()

    assert dropped == 520
    assert store.results == {}
    assert store.ran_at is None
    assert store.source is None
    # And it survives a reload, or the next request brings them all back.
    from vsmail.results import ResultStore

    assert ResultStore(store.path).results == {}


def test_a_sent_reply_leaves_its_lane_for_read(store):
    """A queue that still holds what you have answered stops being a queue."""
    from vsmail.results import READ

    before = store.lanes()
    assert "email_004" in [r.email_id for r in before["BL_COMPARISON"]]
    assert before[READ] == []

    store.mark_sent("email_004")
    after = store.lanes()

    assert "email_004" not in [r.email_id for r in after["BL_COMPARISON"]]
    assert [r.email_id for r in after[READ]] == ["email_004"]
    assert len(after["BL_COMPARISON"]) == len(before["BL_COMPARISON"]) - 1


def test_being_read_survives_a_reload(store):
    from vsmail.results import READ, ResultStore

    store.mark_sent("email_004")
    assert ResultStore(store.path).lanes()[READ][0].email_id == "email_004"


def test_the_category_is_untouched_by_being_read(store):
    """READ is a lane, not a category. The submission carries the category,
    and the schema allows exactly five."""
    store.mark_sent("email_004")
    assert store.results["email_004"].category == "BL_COMPARISON"


def test_marking_an_unknown_email_is_not_an_error(store):
    assert store.mark_sent("email_999") is None


def test_a_gmail_run_keeps_the_message_id(processed, bundle, tmp_path):
    selected = next(item for item in processed if item.verdict.email_id == "email_004")
    record = bundle.get("email_004")
    store = ResultStore(tmp_path / "gmail-results.json")

    store.record(
        [selected],
        {record.email_id: record},
        "gmail",
        {record.email_id: "MSG-004"},
    )

    assert store.results[record.email_id].gmail_message_id == "MSG-004"
    assert ResultStore(store.path).results[record.email_id].gmail_message_id == "MSG-004"


def test_reruns_preserve_delivery_and_gmail_identity(processed, bundle, tmp_path):
    selected = next(item for item in processed if item.verdict.email_id == "email_004")
    record = bundle.get("email_004")
    store = ResultStore(tmp_path / "rerun-results.json")
    store.record(
        [selected],
        {record.email_id: record},
        "gmail",
        {record.email_id: "MSG-004"},
    )
    store.mark_sent(record.email_id, "2026-09-21T00:00:00+00:00")

    store.update_one(selected, record)
    store.record([selected], {record.email_id: record}, "gmail")

    result = store.results[record.email_id]
    assert result.gmail_message_id == "MSG-004"
    assert result.sent_at == "2026-09-21T00:00:00+00:00"
