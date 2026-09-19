#!/usr/bin/env python3
"""Run the pipeline over the bundle and write submission.json."""
from __future__ import annotations

import argparse
import asyncio
import collections
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail import pipeline, submission  # noqa: E402
from vsmail.inbox import DEFAULT_SOURCE, Bundle  # noqa: E402


def make_provider(name: str):
    if name == "mock":
        from vsmail.llm.mock import MockProvider

        return MockProvider()
    if name == "deepseek":
        from vsmail.llm.deepseek import DeepSeekProvider

        return DeepSeekProvider()
    if name == "remote":
        from vsmail.llm.remote import RemoteProvider

        return RemoteProvider()
    raise SystemExit(f"unknown provider: {name}")


def _source(document) -> str:
    """Where a document's values came from — text, or pages read as images."""
    if document is None:
        return "absent"
    if not document.readable:
        return f"unreadable ({document.error})"
    if document.images:
        return f"{len(document.images)} scanned page(s), read as images"
    return f"{len(document.text)} chars of text"


def explain(processed) -> None:
    """Print the evidence behind each verdict.

    For a scan there is no second opinion to check a verdict against, so the
    values actually read are the only way to tell a correct reading from a
    confident-looking invention.
    """
    from vsmail.compare import compare_all

    print("\n" + "=" * 78)
    for item in processed:
        verdict = item.verdict
        print(f"\n{verdict.email_id}  {verdict.category}  {verdict.status}"
              + (f"  ({verdict.review_reason})" if verdict.review_reason else ""))
        print(f"  SI: {_source(item.si)}")
        print(f"  BL: {_source(item.bl)}")
        for concern in item.concerns:
            print(f"  ! {concern}")
        if item.extraction is None:
            print("  (no extraction — decided before reading the documents)")
            continue
        uncertain = set(item.extraction.uncertain_fields)
        for comparison in compare_all(item.extraction):
            mark = "??" if comparison.field in uncertain else ("  " if comparison.equal else "->")
            print(f"  {mark} {comparison.field:<18} SI {comparison.si_value!r}")
            print(f"     {'':<18} BL {comparison.bl_value!r}"
                  + (f"   [{comparison.note}]" if comparison.note else ""))
    print("\n" + "=" * 78)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--provider", default="mock", choices=("mock", "deepseek", "remote"))
    parser.add_argument("--out", default="submission.json")
    parser.add_argument("--concurrency", type=int, default=pipeline.DEFAULT_CONCURRENCY)
    parser.add_argument(
        "--limit",
        type=int,
        help="process only the first N emails — smoke-test a paid provider cheaply",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="EMAIL_ID",
        help="process only these emails, e.g. --only email_004 email_512",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="print the values read from each document, so a verdict can be audited",
    )
    args = parser.parse_args()

    bundle = Bundle(args.source)
    provider = make_provider(args.provider)

    emails = bundle.emails()
    if args.only:
        wanted = set(args.only)
        emails = [e for e in emails if e.email_id in wanted]
        unknown = wanted - {e.email_id for e in emails}
        if unknown:
            raise SystemExit(f"unknown email id(s): {sorted(unknown)}")
    if args.limit:
        emails = emails[: args.limit]
    partial = len(emails) != len(bundle.emails())

    print(f"running {provider.name} over {len(emails)} email(s) from {args.source}")
    if partial:
        print("  (subset run — the result is for inspection, not for submitting)")

    started = time.monotonic()
    try:
        processed = await pipeline.process_all(
            bundle, provider, concurrency=args.concurrency, emails=emails
        )
    finally:
        await provider.aclose()
    elapsed = time.monotonic() - started

    verdicts = [item.verdict for item in processed]
    if args.explain:
        explain(processed)

    result = submission.build(verdicts)
    expected = [e.email_id for e in (emails if partial else bundle.emails())]
    problems = submission.validate(result, expected)
    if problems:
        print(f"\nsubmission is invalid ({len(problems)} problem(s)):")
        for problem in problems[:20]:
            print(f"  {problem}")
        return 1

    path = submission.write(result, args.out)

    categories = collections.Counter(v.category for v in verdicts)
    statuses = collections.Counter(v.status for v in verdicts)
    reasons = collections.Counter(v.review_reason for v in verdicts if v.review_reason)
    defects = collections.Counter(f for v in verdicts for f in v.defect_fields)

    print(f"\n{len(verdicts)} emails in {elapsed:.1f}s -> {path}")
    if partial:
        print("  NOT a submittable file: it covers a subset, not all 520 emails.")
    print("\ncategory      ", dict(categories.most_common()))
    print("status        ", dict(statuses.most_common()))
    print("review reason ", dict(reasons.most_common()))
    print("defect fields ", dict(defects.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
