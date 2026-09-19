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


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--provider", default="mock", choices=("mock", "deepseek", "remote"))
    parser.add_argument("--out", default="submission.json")
    parser.add_argument("--concurrency", type=int, default=pipeline.DEFAULT_CONCURRENCY)
    args = parser.parse_args()

    bundle = Bundle(args.source)
    provider = make_provider(args.provider)
    print(f"running {provider.name} over {args.source}")

    started = time.monotonic()
    try:
        verdicts = await pipeline.run(bundle, provider, concurrency=args.concurrency)
    finally:
        await provider.aclose()
    elapsed = time.monotonic() - started

    result = submission.build(verdicts)
    problems = submission.validate(result, [e.email_id for e in bundle.emails()])
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
    print("\ncategory      ", dict(categories.most_common()))
    print("status        ", dict(statuses.most_common()))
    print("review reason ", dict(reasons.most_common()))
    print("defect fields ", dict(defects.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
