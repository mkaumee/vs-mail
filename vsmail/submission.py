"""Building and checking submission.json.

The graded artifact. Every one of the 520 emails must be present, with
exactly the five keys and only the values the schema allows, so the file is
validated before it is written rather than after it is rejected.
"""
from __future__ import annotations

import json
from pathlib import Path

from vsmail.config import CATEGORIES, FIELDS, REVIEW_REASONS, STATUSES
from vsmail.models import Verdict

_KEYS = {"category", "status", "review_reason", "has_defect", "defect_fields"}


def build(verdicts: list[Verdict]) -> dict[str, dict]:
    return {verdict.email_id: verdict.to_submission_entry() for verdict in verdicts}


def validate(submission: dict, expected_ids: list[str]) -> list[str]:
    """Every way the file could be rejected, reported at once."""
    problems: list[str] = []

    missing = [eid for eid in expected_ids if eid not in submission]
    if missing:
        problems.append(f"{len(missing)} email(s) missing, first: {missing[:3]}")
    extra = [eid for eid in submission if eid not in set(expected_ids)]
    if extra:
        problems.append(f"{len(extra)} unknown email id(s), first: {extra[:3]}")

    for email_id, entry in submission.items():
        where = f"{email_id}:"
        if set(entry) != _KEYS:
            problems.append(f"{where} keys are {sorted(entry)}, expected {sorted(_KEYS)}")
            continue
        if entry["category"] not in CATEGORIES:
            problems.append(f"{where} bad category {entry['category']!r}")
        if entry["status"] not in STATUSES:
            problems.append(f"{where} bad status {entry['status']!r}")
        reason = entry["review_reason"]
        if reason is not None and reason not in REVIEW_REASONS:
            problems.append(f"{where} bad review_reason {reason!r}")
        if not isinstance(entry["has_defect"], bool):
            problems.append(f"{where} has_defect must be a boolean")
        fields = entry["defect_fields"]
        if not isinstance(fields, list) or any(f not in FIELDS for f in fields):
            problems.append(f"{where} bad defect_fields {fields!r}")

        # Internal consistency: these three must tell the same story.
        if entry["status"] == "MISMATCH" and not fields:
            problems.append(f"{where} MISMATCH with no defect_fields")
        if bool(fields) != bool(entry["has_defect"]):
            problems.append(f"{where} has_defect disagrees with defect_fields")
        if (entry["status"] == "NEEDS_REVIEW") != (reason is not None):
            problems.append(f"{where} review_reason must accompany NEEDS_REVIEW only")

    return problems


def write(submission: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(submission, indent=2) + "\n")
    return path
