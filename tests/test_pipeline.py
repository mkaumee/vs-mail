"""End-to-end over the real bundle, with the offline provider."""
import pytest

from vsmail import pipeline, submission
from vsmail.gmail.retry import GmailTemporarilyBusy
from vsmail.llm.mock import MockProvider


@pytest.fixture(scope="module")
def verdicts(bundle):
    import asyncio

    return asyncio.run(pipeline.run(bundle, MockProvider()))


@pytest.fixture(scope="module")
def result(verdicts):
    return submission.build(verdicts)


def test_every_email_gets_an_entry(bundle, result):
    assert len(result) == 520
    assert set(result) == {email.email_id for email in bundle.emails()}


def test_the_submission_validates(bundle, result):
    problems = submission.validate(result, [e.email_id for e in bundle.emails()])
    assert problems == []


def test_email_004_reports_exactly_its_two_defects(result):
    entry = result["email_004"]
    assert entry["status"] == "MISMATCH"
    assert entry["defect_fields"] == ["consignee", "notify_party"]
    assert entry["has_defect"]


@pytest.mark.parametrize(
    "email_id,reason",
    [
        ("email_501", "wrong_doc_type"),
        ("email_502", "wrong_doc_type"),
        ("email_503", "wrong_doc_type"),
        ("email_504", "wrong_doc_type"),
        ("email_505", "wrong_doc_type"),
        ("email_506", "missing_attachment"),
        ("email_507", "missing_attachment"),
        ("email_508", "missing_attachment"),
        ("email_509", "missing_attachment"),
        ("email_510", "missing_attachment"),
        ("email_511", "unreadable"),
        ("email_515", "unreadable"),
        ("email_519", "missing_value"),
        ("email_520", "missing_value"),
    ],
)
def test_each_planted_edge_case_is_escalated_correctly(result, email_id, reason):
    entry = result[email_id]
    assert entry["category"] == "BL_COMPARISON"
    assert entry["status"] == "NEEDS_REVIEW"
    assert entry["review_reason"] == reason


@pytest.mark.parametrize("email_id", ["email_512", "email_513", "email_514"])
def test_scans_are_escalated_rather_than_guessed(result, email_id):
    """The offline provider cannot read an image. It must say so, not guess.

    A vision-capable provider should instead compare these properly, which is
    the clearest difference the model makes over the baseline.
    """
    assert result[email_id]["status"] == "NEEDS_REVIEW"
    assert result[email_id]["review_reason"] == "missing_value"


def test_nothing_outside_comparison_requests_is_escalated(result):
    for email_id, entry in result.items():
        if entry["category"] != "BL_COMPARISON":
            assert entry["status"] == "OK", email_id
            assert entry["review_reason"] is None
            assert entry["defect_fields"] == []


def test_validation_catches_a_broken_entry(bundle, result):
    broken = dict(result)
    broken["email_004"] = dict(broken["email_004"], status="MISMATCH", defect_fields=[])
    problems = submission.validate(broken, [e.email_id for e in bundle.emails()])
    assert any("MISMATCH with no defect_fields" in p for p in problems)


def test_validation_catches_a_missing_email(bundle, result):
    short = {k: v for k, v in result.items() if k != "email_001"}
    problems = submission.validate(short, [e.email_id for e in bundle.emails()])
    assert any("missing" in p for p in problems)


async def test_a_subset_run_processes_only_what_it_is_given(bundle):
    """How a paid provider gets smoke-tested before a full pass."""
    wanted = ["email_004", "email_512"]
    emails = [e for e in bundle.emails() if e.email_id in wanted]
    results = await pipeline.run(bundle, MockProvider(), emails=emails)
    assert [v.email_id for v in results] == wanted


async def test_processing_keeps_the_evidence_behind_a_verdict(bundle):
    """--explain needs the values read, not just the verdict."""
    emails = [e for e in bundle.emails() if e.email_id == "email_004"]
    processed = await pipeline.process_all(bundle, MockProvider(), emails=emails)
    item = processed[0]
    assert item.verdict.status == "MISMATCH"
    assert item.extraction is not None
    assert item.extraction.si["consignee"] == "EAST BRIGHT FZ-LLC"
    assert item.extraction.bl["consignee"] == "UAB NOVAKOPA"
    assert item.si.text and item.bl.text


async def test_processing_reports_real_classification_and_extraction_stages(bundle):
    email = bundle.get("email_004")
    seen = []

    await pipeline.process_email(
        bundle,
        MockProvider(),
        email,
        stage=lambda current, phase: seen.append((current.email_id, phase)),
    )

    assert seen == [
        ("email_004", "classifying"),
        ("email_004", "reading_documents"),
        ("email_004", "extracting"),
        ("email_004", "comparing"),
        ("email_004", "checking_discrepancies"),
    ]


async def test_mailbox_quota_failure_is_not_recorded_as_a_bad_email(bundle, monkeypatch):
    email = bundle.get("email_004")

    def busy(path):
        raise GmailTemporarilyBusy("try later")

    monkeypatch.setattr(bundle, "read_bytes", busy)
    with pytest.raises(GmailTemporarilyBusy, match="try later"):
        await pipeline.process_all(bundle, MockProvider(), emails=[email])


async def test_a_scan_records_that_it_was_read_as_images(bundle):
    """The audit trail must show a scan was images, not empty text."""
    emails = [e for e in bundle.emails() if e.email_id == "email_512"]
    item = (await pipeline.process_all(bundle, MockProvider(), emails=emails))[0]
    assert item.si.images and item.bl.images
    assert item.si.text == ""


async def test_an_email_decided_before_reading_has_no_extraction(bundle):
    """email_511's BL will not open, so nothing was ever extracted."""
    emails = [e for e in bundle.emails() if e.email_id == "email_511"]
    item = (await pipeline.process_all(bundle, MockProvider(), emails=emails))[0]
    assert item.verdict.review_reason == "unreadable"
    assert item.extraction is None
