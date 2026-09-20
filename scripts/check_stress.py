#!/usr/bin/env python3
"""Run the stress inbox and check each case against what it was written for."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail import pipeline  # noqa: E402
from vsmail.inbox import Bundle  # noqa: E402
from vsmail.llm.mock import MockProvider  # noqa: E402

SOURCE = Path("stress data")


def main() -> int:
    expectations = {e["email_id"]: e for e in json.loads((SOURCE / "expectations.json").read_text())}
    bundle = Bundle(SOURCE)
    processed = asyncio.run(pipeline.process_all(bundle, MockProvider()))

    wrong, arguable = [], []
    for item in sorted(processed, key=lambda p: p.verdict.email_id):
        v = item.verdict
        exp = expectations.get(v.email_id, {})
        want, why = exp.get("expect"), exp.get("why", "")
        got = v.status if v.category == "BL_COMPARISON" else v.category
        detail = ", ".join(v.defect_fields) or (v.review_reason or "")
        mark = "  "
        if want is None:
            mark = "??"
        elif got != want:
            mark = "XX"
            (arguable if why.startswith("ARGUABLE") else wrong).append(
                (v.email_id, want, got, why, detail)
            )
        print(f"{mark} {v.email_id}  want {str(want):14} got {got:14} {detail:28} {why[:46]}")

    print()
    if arguable:
        print(f"{len(arguable)} arguable case(s) went the other way:")
        for eid, want, got, why, detail in arguable:
            print(f"   {eid}: expected {want}, got {got} ({detail}) — {why}")
        print()
    if wrong:
        print(f"{len(wrong)} case(s) WRONG:")
        for eid, want, got, why, detail in wrong:
            print(f"   {eid}: expected {want}, got {got} ({detail}) — {why}")
        return 1
    print("every case with a firm expectation behaved as written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
