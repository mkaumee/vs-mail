#!/usr/bin/env python3
"""Score a submission against the hand-written dev set.

This is a dev-set score, not the real one. See vsmail/scoring.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail.scoring import score  # noqa: E402

DEVSET = Path(__file__).resolve().parent.parent / "tests" / "devset.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", nargs="?", default="submission.json")
    parser.add_argument("--devset", default=str(DEVSET))
    parser.add_argument("--quiet", action="store_true", help="hide disagreements")
    args = parser.parse_args()

    submission = json.loads(Path(args.submission).read_text())
    labels = json.loads(Path(args.devset).read_text())["labels"]

    board = score(submission, labels)
    if args.quiet:
        board.disagreements = []
    print(board.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
