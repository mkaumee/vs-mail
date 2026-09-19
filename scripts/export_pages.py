#!/usr/bin/env python3
"""Write a scanned attachment's pages out as PNGs.

The counterpart to `run_submission.py --explain`: that shows what the model
read, this shows what it was looking at. For an image-only document there is
no second opinion to check a verdict against, so the only way to tell a
correct reading from a confident-looking invention is to put the two side by
side.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail.documents import read_document  # noqa: E402
from vsmail.inbox import Bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email_id", help="e.g. email_512")
    parser.add_argument("--role", default="both", choices=("SI", "BL", "both"))
    parser.add_argument("--out", default=".", help="directory to write into")
    args = parser.parse_args()

    bundle = Bundle()
    email = bundle.get(args.email_id)
    roles = ("SI", "BL") if args.role == "both" else (args.role,)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    written = 0
    for role in roles:
        path = email.attachment_for(role)
        if path is None:
            print(f"{args.email_id} has no {role} attachment")
            continue
        document = read_document(path, bundle.read_bytes(path))
        if not document.readable:
            print(f"{path}: unreadable — {document.error}")
            continue
        if not document.images:
            print(f"{path}: has a text layer, no images to export "
                  f"({len(document.text)} chars) — read it directly instead")
            continue
        for index, image in enumerate(document.images, start=1):
            destination = out / f"{args.email_id}_{role}_p{index}.png"
            destination.write_bytes(image)
            print(f"wrote {destination}")
            written += 1

    if not written:
        print("\nnothing exported — none of those attachments are scans")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
