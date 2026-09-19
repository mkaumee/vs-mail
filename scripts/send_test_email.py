#!/usr/bin/env python3
"""Send a genuinely delivered email to the mailbox the agent watches.

Unlike the seeded dataset, this message really travels: it leaves the
account, is delivered by Gmail, and arrives on its own. Run the watcher
alongside it to see it picked up.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail.gmail.client import address, service  # noqa: E402
from vsmail.gmail.send import compose, send  # noqa: E402

_DEFAULT_BODY = (
    "Dear Team,\n\n"
    "Please compare the SI and draft BL for PSGSE4981829 and confirm.\n\n"
    "Thank you."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", help="defaults to the authorised mailbox itself")
    parser.add_argument("--subject", default="TO CONFIRM DOCS _ PSGSE4981829")
    parser.add_argument("--body", default=_DEFAULT_BODY)
    parser.add_argument(
        "--attach", nargs="*", type=Path, default=[], help="files to attach"
    )
    args = parser.parse_args()

    svc = service()
    recipient = args.to or address(svc)
    message_id = send(svc, compose(recipient, args.subject, args.body, args.attach))
    print(f"sent to {recipient} (id {message_id})")
    print("It has to be delivered, so give it a few seconds to arrive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
