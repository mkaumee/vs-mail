"""Scoring, and the dev set it scores against."""
import json
from pathlib import Path

import pytest

from vsmail.config import CATEGORIES, FIELDS, REVIEW_REASONS, STATUSES
from vsmail.scoring import score

DEVSET = Path(__file__).parent / "devset.json"


@pytest.fixture(scope="module")
def labels():
    return json.loads(DEVSET.read_text())["labels"]


def test_the_devset_states_it_is_not_ground_truth():
    readme = json.loads(DEVSET.read_text())["_README"]
    assert "NOT GROUND TRUTH" in readme


def test_every_label_is_well_formed(labels):
    for email_id, label in labels.items():
        assert label["category"] in CATEGORIES, email_id
        assert label["status"] in STATUSES, email_id
        reason = label["review_reason"]
        assert reason is None or reason in REVIEW_REASONS, email_id
        assert all(f in FIELDS for f in label["defect_fields"]), email_id
        assert (label["status"] == "NEEDS_REVIEW") == (reason is not None), email_id
        assert bool(label["defect_fields"]) == (label["status"] == "MISMATCH"), email_id


def test_the_devset_covers_every_category(labels):
    assert {label["category"] for label in labels.values()} == set(CATEGORIES)


def test_the_devset_covers_every_review_reason(labels):
    reasons = {label["review_reason"] for label in labels.values()} - {None}
    assert reasons == set(REVIEW_REASONS)


def test_the_scans_are_labelled_from_their_rasterized_pages(labels):
    """Read by eye via scripts/export_pages.py. All three agree on all seven
    fields, so a provider that can read them should return OK."""
    for email_id in ("email_512", "email_513", "email_514"):
        assert labels[email_id]["status"] == "OK"
        assert labels[email_id]["defect_fields"] == []


def test_a_perfect_submission_scores_one(labels):
    submission = {
        email_id: dict(label, has_defect=bool(label["defect_fields"]))
        for email_id, label in labels.items()
    }
    board = score(submission, labels)
    assert board.devset_score == pytest.approx(1.0)
    assert board.disagreements == []


def test_a_false_alarm_costs_precision(labels):
    """Flagging a field that matches must hurt, not be free."""
    submission = {
        email_id: dict(label, has_defect=bool(label["defect_fields"]))
        for email_id, label in labels.items()
    }
    submission["email_055"] = {
        "category": "BL_COMPARISON",
        "status": "MISMATCH",
        "review_reason": None,
        "has_defect": True,
        "defect_fields": ["gross_weight_kg"],
    }
    board = score(submission, labels)
    assert board.defect_f1 < 1.0
    assert board.end_to_end_f1 < 1.0
    assert any("email_055" in line for line in board.disagreements)


def test_catching_most_of_a_defect_is_not_catching_it(labels):
    submission = {
        email_id: dict(label, has_defect=bool(label["defect_fields"]))
        for email_id, label in labels.items()
    }
    # email_025 has two defects; report only one.
    submission["email_025"] = dict(submission["email_025"], defect_fields=["container_count"])
    board = score(submission, labels)
    assert board.end_to_end_f1 < 1.0, "an incomplete defect list must not count as caught"


def test_a_rare_category_weighs_as_much_as_a_common_one(labels):
    """Macro-averaging is what makes SPAM matter as much as BL_COMPARISON."""
    submission = {
        email_id: dict(label, has_defect=bool(label["defect_fields"]))
        for email_id, label in labels.items()
    }
    spam = [e for e, l in labels.items() if l["category"] == "SPAM"]
    for email_id in spam:
        submission[email_id] = dict(submission[email_id], category="GENERAL")
    board = score(submission, labels)
    # Five emails out of 48 is ~10% of the set but costs far more than that.
    assert board.classification_macro_f1 < 0.85


def test_the_mock_baseline_disagrees_only_where_it_cannot_see(bundle, labels):
    """The offline provider matches our reading everywhere except the scans.

    It escalates those three rather than guessing, which is the correct
    behaviour for a provider without vision — but it is still a disagreement,
    and the dev set records it as one instead of hiding it.
    """
    import asyncio

    from vsmail import pipeline, submission as sub
    from vsmail.llm.mock import MockProvider

    verdicts = asyncio.run(pipeline.run(bundle, MockProvider()))
    board = score(sub.build(verdicts), labels)

    scans = {"email_512", "email_513", "email_514"}
    for line in board.disagreements:
        assert line.split()[0] in scans, f"unexpected disagreement: {line}"
    assert len(board.disagreements) == len(scans)
    assert board.review_accuracy < 1.0, "the blind spot must show in the score"
