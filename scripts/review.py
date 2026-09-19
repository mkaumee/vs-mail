#!/usr/bin/env python3
"""Work the queue of cases waiting on a person.

The counterpart to the pipeline: it decides what it cannot settle, this is
where a person settles it. Supplying a value re-runs the comparison over it
rather than writing a verdict by hand.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail.compare import compare_field  # noqa: E402
from vsmail.config import FIELDS  # noqa: E402
from vsmail.review import SEVERITY, ReviewStore  # noqa: E402

_BANDS = {3: "critical", 2: "high", 1: "medium"}


def _pairs(values: list[str]) -> tuple[dict, dict]:
    """Parse `si.gross_weight_kg=235,550 KG` into per-side dictionaries."""
    si: dict[str, str] = {}
    bl: dict[str, str] = {}
    for item in values:
        if "=" not in item or "." not in item.split("=", 1)[0]:
            raise SystemExit(f"expected side.field=value, got {item!r}")
        target, value = item.split("=", 1)
        side, _, name = target.partition(".")
        if side not in ("si", "bl"):
            raise SystemExit(f"side must be si or bl, got {side!r}")
        if name not in FIELDS:
            raise SystemExit(f"{name!r} is not a compared field; expected one of {', '.join(FIELDS)}")
        (si if side == "si" else bl)[name] = value
    return si, bl


def cmd_list(store: ReviewStore, args) -> int:
    queue = store.queue()
    if not queue:
        if not store.path.is_file():
            print(f"no review store at {store.path} — nothing has been processed yet.")
            print("Run the pipeline first:")
            print("  python scripts/run_submission.py --provider mock")
        else:
            print("queue is empty — nothing is waiting on a person")
        return 0
    print(f"{len(queue)} case(s) waiting, worst first\n")
    for case in queue:
        band = _BANDS.get(case.severity, "medium")
        fields = ", ".join(case.evidence.get("fields_at_issue") or []) or "—"
        print(f"  {case.email_id:<12} {band:<9} {case.reason:<20} {fields}")
    return 0


def cmd_show(store: ReviewStore, args) -> int:
    case = store.get(args.email_id)
    if case is None:
        raise SystemExit(
            f"no case for {args.email_id}. Run `python scripts/review.py list` to "
            "see what is waiting."
        )
    evidence = case.evidence
    print(f"{case.email_id}  {case.state}  ({case.reason})")
    print(f"  category   {evidence.get('category')}  status {evidence.get('status')}")
    print(f"  SI         {evidence.get('si')}  {evidence.get('si_path') or ''}")
    print(f"  BL         {evidence.get('bl')}  {evidence.get('bl_path') or ''}")
    for concern in evidence.get("concerns") or []:
        print(f"  ! {concern}")
    print()
    for name in FIELDS:
        value = (evidence.get("values") or {}).get(name)
        if not value:
            continue
        # Mark what the comparator concluded, not whether the strings differ.
        # "NHAVA SHEVA, INDIA" against "NHAVA SHEVA, INDIA (INNSA)" is a match,
        # and flagging it here would show a reviewer a defect that is not one.
        comparison = compare_field(name, value["si"], value["bl"])
        mark = "??" if value.get("uncertain") else ("  " if comparison.equal else "->")
        note = f"   [{comparison.note}]" if comparison.note else ""
        print(f"  {mark} {name:<18} SI {value['si']!r}")
        print(f"     {'':<18} BL {value['bl']!r}{note}")
    if case.corrections.get("si") or case.corrections.get("bl"):
        print("\n  corrections:", case.corrections)
    if case.settled:
        print("\n  settled by hand:", case.settled)
    if case.audit:
        print("\n  audit:")
        for entry in case.audit:
            print(f"    {entry['at']}  {entry['by']:<10} {entry['action']:<10} {entry['detail']}")
    return 0


def cmd_resolve(store: ReviewStore, args) -> int:
    si, bl = _pairs(args.supply or [])
    settle = None
    if args.settle_status:
        settle = {
            "status": args.settle_status,
            "defect_fields": args.settle_fields or [],
            "review_reason": args.settle_reason,
        }
    if not (si or bl or settle or args.confirm or args.note):
        raise SystemExit("nothing to record: pass --supply, --confirm, --settle-status or --note")

    try:
        case = store.resolve(
            args.email_id,
            by=args.by,
            confirm=args.confirm,
            si=si,
            bl=bl,
            settle=settle,
            note=args.note or "",
        )
    except KeyError:
        raise SystemExit(
            f"no case for {args.email_id}. Run `python scripts/review.py list` to "
            "see what is waiting, or run the pipeline first to open cases."
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(f"{case.email_id} resolved by {args.by}")
    for entry in case.audit[-4:]:
        print(f"  {entry['action']:<10} {entry['detail']}")
    if si or bl:
        print("\nRe-run the pipeline to compare the corrected values:")
        print("  python scripts/run_submission.py --provider mock")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="review.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="the queue, worst first")

    show = sub.add_parser("show", help="one case with its evidence")
    show.add_argument("email_id")

    resolve = sub.add_parser("resolve", help="record a decision")
    resolve.add_argument("email_id")
    resolve.add_argument("--by", default="reviewer", help="who is deciding")
    resolve.add_argument(
        "--supply",
        nargs="+",
        metavar="SIDE.FIELD=VALUE",
        help="supply or correct a value, e.g. si.gross_weight_kg='235,550 KG'",
    )
    resolve.add_argument("--confirm", action="store_true", help="the escalation was right")
    resolve.add_argument("--note", help="free text for the audit trail")
    resolve.add_argument(
        "--settle-status",
        choices=("OK", "MISMATCH", "NEEDS_REVIEW"),
        help="force an outcome without supplying values (bypasses the comparator)",
    )
    resolve.add_argument("--settle-fields", nargs="*", choices=list(FIELDS))
    resolve.add_argument("--settle-reason")

    args = parser.parse_args()
    store = ReviewStore(args.store)
    return {"list": cmd_list, "show": cmd_show, "resolve": cmd_resolve}[args.command](store, args)


if __name__ == "__main__":
    raise SystemExit(main())
