#!/usr/bin/env python3
"""Compare two submissions and say what changed.

With no ground truth, a diff between providers is the sharpest signal we
have. It shows where they disagree; which one is right still has to be
settled by reading the documents.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _line(entry: dict) -> str:
    parts = [entry["status"]]
    if entry.get("review_reason"):
        parts.append(f"({entry['review_reason']})")
    if entry.get("defect_fields"):
        parts.append(", ".join(entry["defect_fields"]))
    return "  ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", help="baseline, e.g. submission.mock.json")
    parser.add_argument("right", help="candidate, e.g. submission.deepseek.json")
    args = parser.parse_args()

    left = json.loads(Path(args.left).read_text())
    right = json.loads(Path(args.right).read_text())
    shared = [k for k in left if k in right]

    changed = [k for k in shared if left[k] != right[k]]
    print(f"{len(changed)} of {len(shared)} entries differ\n")

    buckets: dict[str, list[str]] = collections.defaultdict(list)
    for email_id in changed:
        a, b = left[email_id], right[email_id]
        if a["category"] != b["category"]:
            buckets["category changed"].append(email_id)
        elif a["status"] != b["status"]:
            if b["status"] == "NEEDS_REVIEW":
                buckets["escalated by the candidate only"].append(email_id)
            elif a["status"] == "NEEDS_REVIEW":
                buckets["escalated by the baseline only"].append(email_id)
            else:
                buckets["status changed"].append(email_id)
        else:
            buckets["same status, different defect fields"].append(email_id)

    #: Where one side gives up and the other does not is the most telling
    #: difference, so it is reported first.
    order = [
        "escalated by the candidate only",
        "escalated by the baseline only",
        "same status, different defect fields",
        "status changed",
        "category changed",
    ]
    for name in order:
        ids = buckets.get(name)
        if not ids:
            continue
        print(f"=== {name} ({len(ids)})")
        for email_id in sorted(ids):
            print(f"  {email_id}")
            print(f"     {Path(args.left).stem:>22}  {_line(left[email_id])}")
            print(f"     {Path(args.right).stem:>22}  {_line(right[email_id])}")
        print()

    for label, data in ((args.left, left), (args.right, right)):
        reasons = collections.Counter(
            e["review_reason"] for e in data.values() if e.get("review_reason")
        )
        print(f"{label}: review reasons {dict(sorted(reasons.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
