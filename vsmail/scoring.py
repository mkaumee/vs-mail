"""Scoring a submission against a set of labels.

⚠️ This produces a **dev-set score, not the real one.** We have no ground
truth. Everything here grades a submission against labels we wrote
ourselves, so the number says "did this change make things better or worse
by our own reading", never "this is what we will score".

The field is called `devset_score` for that reason, and it should keep that
name wherever it is displayed. A number reads as truth, and a confident
number computed against our own guesses is worse than no number at all.

Where our labels and a submission disagree, re-read the label before
changing the pipeline.

The formula mirrors the one the organizers state:

    50% end-to-end + 30% Stage-1 macro-F1 + 20% Stage-3 defect-F1

with NEEDS_REVIEW handling reported separately as a reliability axis.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from vsmail.config import CATEGORIES


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float
    support: int


def _prf(true_positive: int, false_positive: int, false_negative: int, support: int) -> PRF:
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return PRF(precision, recall, f1, support)


@dataclass
class Scoreboard:
    """What a run scored against our labels. Never a real score."""

    devset_score: float
    classification_macro_f1: float
    defect_f1: float
    end_to_end_f1: float
    per_category: dict[str, PRF] = field(default_factory=dict)
    review_accuracy: float = 0.0
    review_support: int = 0
    labelled: int = 0
    disagreements: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"dev-set score      {self.devset_score:.3f}   (against our own labels, not ground truth)",
            f"  classification   {self.classification_macro_f1:.3f}  macro-F1, weight 0.30",
            f"  defect fields    {self.defect_f1:.3f}  F1, weight 0.20",
            f"  end to end       {self.end_to_end_f1:.3f}  F1, weight 0.50",
            f"  review reasons   {self.review_accuracy:.3f}  over {self.review_support} escalations"
            " (reliability, unweighted)",
            f"  labelled emails  {self.labelled}",
            "",
            "per category:",
        ]
        for name, prf in self.per_category.items():
            lines.append(
                f"  {name:<16} P {prf.precision:.2f}  R {prf.recall:.2f}  "
                f"F1 {prf.f1:.2f}  n={prf.support}"
            )
        if self.disagreements:
            lines += ["", f"disagreements ({len(self.disagreements)}):"]
            lines += [f"  {line}" for line in self.disagreements[:25]]
        return "\n".join(lines)


def score(submission: dict, labels: dict) -> Scoreboard:
    """Grade a submission against hand-written labels."""
    shared = [eid for eid in labels if eid in submission]

    # Stage 1: classification, macro-averaged so a rare category counts as
    # much as a common one.
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    support: Counter[str] = Counter()
    disagreements: list[str] = []

    for email_id in shared:
        want = labels[email_id]["category"]
        got = submission[email_id]["category"]
        support[want] += 1
        if want == got:
            tp[want] += 1
        else:
            fn[want] += 1
            fp[got] += 1
            disagreements.append(f"{email_id} category: labelled {want}, produced {got}")

    per_category = {
        name: _prf(tp[name], fp[name], fn[name], support[name])
        for name in CATEGORIES
        if support[name] or fp[name]
    }
    macro_f1 = (
        sum(prf.f1 for prf in per_category.values()) / len(per_category)
        if per_category
        else 0.0
    )

    # Stage 3: defect fields, over every (email, field) pair either side flags.
    d_tp = d_fp = d_fn = 0
    for email_id in shared:
        want = set(labels[email_id].get("defect_fields") or [])
        got = set(submission[email_id].get("defect_fields") or [])
        d_tp += len(want & got)
        d_fp += len(got - want)
        d_fn += len(want - got)
        if want != got:
            disagreements.append(
                f"{email_id} defects: labelled {sorted(want) or '[]'}, produced {sorted(got) or '[]'}"
            )
    defect = _prf(d_tp, d_fp, d_fn, d_tp + d_fn)

    # End to end: an email with defects counts only when it was classified as
    # a comparison, reported as a mismatch, and named exactly the right
    # fields. Catching six of seven defects is not catching the defect.
    e_tp = e_fp = e_fn = 0
    for email_id in shared:
        label, entry = labels[email_id], submission[email_id]
        want = bool(label.get("defect_fields"))
        got = entry["status"] == "MISMATCH" and entry["category"] == "BL_COMPARISON"
        exact = set(label.get("defect_fields") or []) == set(entry.get("defect_fields") or [])
        if want and got and exact:
            e_tp += 1
        elif got and not (want and exact):
            e_fp += 1
        elif want:
            e_fn += 1
    end_to_end = _prf(e_tp, e_fp, e_fn, e_tp + e_fn)

    # Reliability: when we escalate, is it for the right reason?
    review_right = review_total = 0
    for email_id in shared:
        want_reason = labels[email_id].get("review_reason")
        got_reason = submission[email_id].get("review_reason")
        if want_reason or got_reason:
            review_total += 1
            review_right += want_reason == got_reason
            if want_reason != got_reason:
                disagreements.append(
                    f"{email_id} review: labelled {want_reason}, produced {got_reason}"
                )
    review_accuracy = review_right / review_total if review_total else 0.0

    total = 0.50 * end_to_end.f1 + 0.30 * macro_f1 + 0.20 * defect.f1
    return Scoreboard(
        devset_score=total,
        classification_macro_f1=macro_f1,
        defect_f1=defect.f1,
        end_to_end_f1=end_to_end.f1,
        per_category=per_category,
        review_accuracy=review_accuracy,
        review_support=review_total,
        labelled=len(shared),
        disagreements=disagreements,
    )
