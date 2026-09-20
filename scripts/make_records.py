#!/usr/bin/env python3
"""Generate the fabricated invoice, charge and GR records.

⚠️ Every amount, date and status here is invented. What is *not* invented is
the keys: the invoice numbers and booking references are read out of the
bundle's own emails, so a question about invoice 5250075931 finds a record
rather than a gap. Without that the answering side would be demonstrably
useless on the actual inbox.

Deterministic — seeded from the reference itself — so regenerating produces
the same records and a diff stays readable.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsmail.inbox import Bundle  # noqa: E402

PORTS = {
    "5AKR": ("NHAVA SHEVA, INDIA", "INR"), "5ALT": ("JEBEL ALI, UAE", "AED"),
    "5RSG": ("SINGAPORE", "SGD"), "5RUS": ("HOUSTON, US", "USD"),
    "5RCY": ("CONAKRY, GUINEA", "USD"), "5APH": ("MOMBASA, KENYA", "USD"),
    "5RVN": ("HO CHI MINH CITY, VIETNAM", "USD"), "5RAE": ("KLAIPEDA, LITHUANIA", "EUR"),
    "5RFR": ("SAVANNAH, US", "USD"), "5SUS": ("NEW YORK, US", "USD"),
    "5AAT": ("VALPARAISO, CHILE", "USD"), "5RMY": ("PORT KLANG, MALAYSIA", "MYR"),
    "5RVA": ("APAPA, NIGERIA", "USD"), "5AIE": ("BRISBANE, AUSTRALIA", "AUD"),
}
INCOTERMS = ("CFR", "FOB", "CIF", "CFR", "CFR")
GR_STATES = (
    ("posted", None),
    ("not posted", "awaiting confirmation from the receiving party"),
    ("not posted", "quantity mismatch against the purchase order"),
    ("not posted", "the purchase order was closed before delivery"),
)


def rng(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def pick(key: str, options):
    return options[rng(key) % len(options)]


def money(key: str, low: int, high: int) -> float:
    return round(low + (rng(key) % (high - low)) + (rng(key + "c") % 100) / 100, 2)


def main() -> None:
    bundle = Bundle()
    invoices: dict[str, dict] = {}
    bookings: dict[str, dict] = {}

    for email in bundle.emails():
        text = f"{email.subject or ''} {email.body or ''}"
        refs = set(re.findall(r"\b(\d[A-Z]{3}-\d{5})\b", text))
        nums = set(re.findall(r"\b(52\d{8})\b", text))

        for ref in refs:
            if ref in bookings:
                continue
            prefix = ref.split("-")[0]
            port, currency = PORTS.get(prefix, ("SINGAPORE", "USD"))
            discharged = date(2026, 1, 8) + timedelta(days=rng(ref) % 60)
            free_days = pick(ref + "f", (7, 7, 7, 3, 5))
            held = pick(ref + "h", (0, 0, 2, 4, 6, 9, 12))
            rate = pick(ref + "r", (45.0, 55.0, 60.0, 75.0, 90.0))
            containers = [f"{pick(ref + str(i) + 'p', ('MSKU', 'OOLU', 'TGHU', 'CMAU'))}"
                          f"{rng(ref + str(i)) % 9000000 + 1000000}"
                          for i in range(pick(ref + "n", (1, 1, 2, 2, 3)))]
            chargeable = max(0, held)
            bookings[ref] = {
                "booking": ref,
                "port_of_discharge": port,
                "currency": currency,
                "incoterm": pick(ref + "i", INCOTERMS),
                "containers": containers,
                "discharged_on": discharged.isoformat(),
                "free_days": free_days,
                "days_held_beyond_free_time": chargeable,
                "daily_rate": rate,
                "detention_total": round(rate * chargeable * len(containers), 2),
            }

        for num in nums:
            if num in invoices:
                continue
            ref = sorted(refs)[0] if refs else None
            book = bookings.get(ref) if ref else None
            currency = book["currency"] if book else "USD"
            freight = money(num + "fr", 800, 4200)
            othc = money(num + "ot", 120, 320)
            dthc = money(num + "dt", 140, 380)
            doc = money(num + "dc", 35, 75)
            state, reason = pick(num + "g", GR_STATES)
            invoices[num] = {
                "invoice": num,
                "booking": ref,
                "currency": currency,
                "incoterm": book["incoterm"] if book else pick(num + "i", INCOTERMS),
                "issued_on": (date(2026, 1, 5) + timedelta(days=rng(num) % 70)).isoformat(),
                "lines": [
                    {"description": "Ocean freight", "amount": freight},
                    {"description": "Origin terminal handling (OTHC)", "amount": othc},
                    {"description": "Destination terminal handling (DTHC)", "amount": dthc},
                    {"description": "Documentation fee", "amount": doc},
                ],
                "total": round(freight + othc + dthc + doc, 2),
                "pgi_posted": True,
                "gr_status": state,
                "gr_blocked_because": reason,
                "billing_status": "billed" if state == "posted" else "blocked",
            }

    out = {
        "_warning": (
            "FABRICATED. Invoice numbers and booking references are real ones "
            "from the bundle's emails; every amount, date and status attached "
            "to them was generated. Never present these as actual records."
        ),
        "invoices": invoices,
        "bookings": bookings,
    }
    path = Path("knowledge/records.json")
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"{len(invoices)} invoices, {len(bookings)} bookings -> {path}")


if __name__ == "__main__":
    main()
