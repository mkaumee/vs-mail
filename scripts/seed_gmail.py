#!/usr/bin/env python3
"""Load the bundle's 520 emails into a real Gmail mailbox."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail.gmail import seed as seeding  # noqa: E402
from vsmail.gmail.client import address, service_or_exit  # noqa: E402
from vsmail.inbox import Bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="bin everything seeded before")
    parser.add_argument("--limit", type=int, help="seed only the first N, to try it out")
    parser.add_argument("--source", default=None, help="bundle folder")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation")
    args = parser.parse_args()

    svc = service_or_exit()
    mailbox = address(svc)

    # Seeding the wrong account is tedious to undo, so it is always named.
    print(f"mailbox: {mailbox}")
    if not args.yes:
        action = "bin everything previously seeded" if args.reset else "insert messages"
        if input(f"About to {action} in {mailbox}. Continue? [y/N] ").strip().lower() != "y":
            print("stopped")
            return 1

    if args.reset:
        result = seeding.reset(svc)
        print(f"moved {result['trashed']} seeded message(s) to the bin")
        return 0

    bundle = Bundle(args.source) if args.source else Bundle()
    result = seeding.seed(svc, bundle, limit=args.limit)
    print(f"inserted {result['inserted']} message(s) into {result['mailbox']}")
    if result["failed"]:
        print(f"{len(result['failed'])} failed:")
        for email_id, why in result["failed"][:10]:
            print(f"  {email_id}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
