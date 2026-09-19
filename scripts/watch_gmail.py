#!/usr/bin/env python3
"""Watch a real mailbox and process whatever arrives.

Polls rather than subscribing to push notifications. Pub/Sub would need a
public HTTPS endpoint and a Cloud topic — a great deal of setup to save a few
seconds of latency nobody watching will notice.

Seen message ids are remembered on disk, so a restart does not reprocess the
mailbox and a demo can be re-run without paying for 520 emails again.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail import pipeline  # noqa: E402
from vsmail.gmail.client import address, service_or_exit  # noqa: E402
from vsmail.gmail.labels import Labels, labels_for  # noqa: E402
from vsmail.gmail.message import to_record  # noqa: E402
from vsmail.gmail.source import CACHE, GmailSource  # noqa: E402


def _provider(name: str):
    if name == "deepseek":
        from vsmail.llm.deepseek import DeepSeekProvider

        return DeepSeekProvider()
    if name == "remote":
        from vsmail.llm.remote import RemoteProvider

        return RemoteProvider()
    from vsmail.llm.mock import MockProvider

    return MockProvider()


def _seen_path(cache: Path) -> Path:
    return cache / "seen.json"


def _load_seen(cache: Path) -> set[str]:
    path = _seen_path(cache)
    return set(json.loads(path.read_text())) if path.is_file() else set()


def _save_seen(cache: Path, seen: set[str]) -> None:
    path = _seen_path(cache)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen)))


async def _handle(source, provider, labels, message_id: str, write_labels: bool) -> str:
    message = source._message(message_id)
    record = to_record(message)
    processed = await pipeline.process_email(source, provider, record)
    entry = processed.verdict.to_submission_entry()

    line = f"{record.email_id:<22} {entry['category']:<15} {entry['status']}"
    if entry["review_reason"]:
        line += f"  ({entry['review_reason']})"
    if entry["defect_fields"]:
        line += "  " + ", ".join(entry["defect_fields"])
    if write_labels:
        labels.apply(message_id, labels_for(entry))
    return line


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="mock", choices=("mock", "deepseek", "remote"))
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between polls")
    parser.add_argument("--no-labels", action="store_true", help="do not write labels back")
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help="also process everything already in the mailbox, not just new arrivals",
    )
    args = parser.parse_args()

    svc = service_or_exit()
    source = GmailSource(svc)
    labels = Labels(svc)
    provider = _provider(args.provider)
    cache = CACHE

    seen = _load_seen(cache)
    if not args.catch_up and not seen:
        # First run with no history: take everything as already seen, so the
        # watcher reports genuinely new mail instead of replaying the mailbox.
        seen = set(source.message_ids())
        _save_seen(cache, seen)
        print(f"{len(seen)} existing message(s) marked as seen; watching for new mail")

    print(f"watching {address(svc)} every {args.interval:g}s with {provider.name}")
    print("Ctrl-C to stop.\n")

    try:
        while True:
            try:
                current = source.message_ids()
            except Exception as exc:
                print(f"  (could not list the mailbox: {exc})")
                time.sleep(args.interval)
                continue

            fresh = [mid for mid in current if mid not in seen]
            for message_id in fresh:
                try:
                    print("  " + await _handle(
                        source, provider, labels, message_id, not args.no_labels
                    ))
                except Exception as exc:
                    print(f"  {message_id}: failed — {exc}")
                seen.add(message_id)
            if fresh:
                _save_seen(cache, seen)
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        await provider.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
