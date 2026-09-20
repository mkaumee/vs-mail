#!/usr/bin/env python3
"""Embed the knowledge corpus and write the vector index.

Run after changing anything under knowledge/. The result is committed so a
deploy does not have to embed 531 chunks at boot.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail.knowledge.index import INDEX, build  # noqa: E402

if __name__ == "__main__":
    count = build()
    size = INDEX.stat().st_size / 1024
    print(f"embedded {count} chunks -> {INDEX} ({size:.0f} KB)")
