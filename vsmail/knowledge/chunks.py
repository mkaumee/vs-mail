"""Turning the reference material into retrievable pieces.

Split on markdown headings rather than a fixed window. These documents are
already organised by topic — "Free time", "Disputing", "Cancelling an invoice
and reversing the PGI" — and a heading is a better boundary than a character
count because it is where the subject actually changes. A fixed window cuts
tables in half.

Records are rendered to prose before embedding. A JSON blob embeds badly: the
vector ends up dominated by the key names, which are identical across every
record, so every invoice looks alike. Written as a sentence, an invoice reads
like the question that would ask about it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Where the corpus lives.
KNOWLEDGE = Path(__file__).resolve().parent.parent.parent / "knowledge"

#: Chunks below this are heading-only fragments with nothing under them.
MIN_CHARS = 80


@dataclass(frozen=True)
class Chunk:
    """One retrievable piece, with enough to cite it."""

    id: str
    source: str
    heading: str
    text: str
    #: True when the content was invented for the demo. Carried all the way to
    #: the screen — an answer drawn from a fabricated record has to say so.
    fabricated: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "heading": self.heading,
            "text": self.text,
            "fabricated": self.fabricated,
        }


def split_markdown(path: Path) -> list[Chunk]:
    """One chunk per `##` section, with the document title kept as context."""
    lines = path.read_text().splitlines()
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("# ")), path.stem)

    chunks: list[Chunk] = []
    heading = title
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if len(text) >= MIN_CHARS:
            chunks.append(
                Chunk(
                    id=f"{path.stem}#{len(chunks)}",
                    source=path.name,
                    heading=heading,
                    # The heading rides along in the embedded text: "Free time"
                    # alone carries the topic that the body below assumes.
                    text=f"{title} — {heading}\n\n{text}",
                )
            )

    for line in lines:
        if line.startswith("## "):
            flush()
            heading = line.lstrip("# ").strip()
            body = []
        elif not line.startswith("# "):
            body.append(line)
    flush()
    return chunks


def _invoice_text(inv: dict) -> str:
    lines = ", ".join(f"{l['description']} {inv['currency']} {l['amount']:,.2f}"
                      for l in inv["lines"])
    gr = inv["gr_status"]
    because = f" because {inv['gr_blocked_because']}" if inv.get("gr_blocked_because") else ""
    return (
        f"Invoice {inv['invoice']} for booking {inv['booking']}, issued "
        f"{inv['issued_on']} on {inv['incoterm']} terms. Charge breakdown: "
        f"{lines}. Total {inv['currency']} {inv['total']:,.2f}. "
        f"Goods receipt is {gr}{because}. Billing status: {inv['billing_status']}."
    )


def _booking_text(b: dict) -> str:
    containers = ", ".join(b["containers"])
    if b["days_held_beyond_free_time"]:
        detention = (
            f"Held {b['days_held_beyond_free_time']} day(s) beyond the "
            f"{b['free_days']} days free time, charged at {b['currency']} "
            f"{b['daily_rate']:,.2f} per container per day. Detention and "
            f"demurrage total {b['currency']} {b['detention_total']:,.2f}."
        )
    else:
        detention = (
            f"Returned within the {b['free_days']} days free time; no "
            f"detention or demurrage is due."
        )
    return (
        f"Booking {b['booking']} to {b['port_of_discharge']} on "
        f"{b['incoterm']} terms. Container(s) {containers}, discharged "
        f"{b['discharged_on']}. {detention}"
    )


def load_records(path: Path | None = None) -> list[Chunk]:
    """The fabricated records, as sentences rather than JSON."""
    path = path or (KNOWLEDGE / "records.json")
    if not path.is_file():
        return []
    data = json.loads(path.read_text())

    chunks = []
    for number, inv in sorted(data.get("invoices", {}).items()):
        chunks.append(
            Chunk(f"invoice:{number}", "records.json", f"Invoice {number}",
                  _invoice_text(inv), fabricated=True)
        )
    for ref, book in sorted(data.get("bookings", {}).items()):
        chunks.append(
            Chunk(f"booking:{ref}", "records.json", f"Booking {ref}",
                  _booking_text(book), fabricated=True)
        )
    return chunks


def load_all(directory: Path | None = None) -> list[Chunk]:
    """Everything retrievable: the policy documents and the records."""
    directory = directory or KNOWLEDGE
    docs: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            # Describes the corpus rather than being part of it. Retrieving it
            # would answer a customer's question with our own file listing.
            continue
        docs.extend(split_markdown(path))
    return docs + load_records(directory / "records.json")
