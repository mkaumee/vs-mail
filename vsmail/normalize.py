"""Turning written values into comparable ones.

This is where false alarms are won or lost. "22,000 KG" and "22000 kgs" are
the same weight and must not be reported as a defect; "6 x 20'GP" and
"5 x 20'GP" differ by one container and must be.

Normalization is deliberately conservative. Legal suffixes are kept, because
"APRIL FINE PAPER TRADING" and "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE"
are different entities and collapsing them would hide a real defect.
"""
from __future__ import annotations

import re

#: A UN/LOCODE or similar code in trailing parentheses.
_PARENTHETICAL = re.compile(r"\(([^)]*)\)")

#: Weight units, as a multiplier into kilograms.
_UNITS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\b(?:MT|M/?TONS?|METRIC\s*TONS?|TONNES?)\b", re.I), 1000.0),
    (re.compile(r"\b(?:KGS?|KILOS?|KILOGRAMS?)\b", re.I), 1.0),
)


def normalize_name(value: str | None) -> str | None:
    """Fold case, punctuation and spacing on a party or place name.

    Punctuation becomes a space rather than vanishing, so "KPP-ANTALIS" and
    "KPP ANTALIS" agree while distinct words never run together.
    """
    if value is None:
        return None
    folded = re.sub(r"[^0-9A-Za-z]+", " ", value).strip().upper()
    return re.sub(r"\s+", " ", folded) or None


def normalize_port(value: str | None) -> str | None:
    """Normalize a port, ignoring any code in parentheses.

    The code cannot be trusted here. In email_119 the SI reads "PORT KLANG
    (WESTPORT), MALAYSIA (MYPKG)" while the BL reads "SINGAPORE, SINGAPORE
    (MYPKG)": the code was carried over unchanged while the port itself was
    altered. Comparing on codes would hide that defect, so the name decides
    and the code is dropped.
    """
    if value is None:
        return None
    # "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)" keeps WESTPORT, which is part
    # of the port's name, and drops only a trailing all-caps code.
    without_code = re.sub(r"\(\s*[A-Z]{5}\s*\)\s*$", "", value.strip())
    return normalize_name(without_code)


def port_code(value: str | None) -> str | None:
    """The UN/LOCODE a port value carries, for display only."""
    if not value:
        return None
    codes = [m for m in _PARENTHETICAL.findall(value) if re.fullmatch(r"[A-Z]{5}", m.strip())]
    return codes[-1].strip() if codes else None


def normalize_container_count(value: str | None) -> int | None:
    """The number of containers out of "6 x 40'HC" or "6"."""
    if value is None:
        return None
    match = re.search(r"\d+", value)
    return int(match.group()) if match else None


def normalize_weight_kg(value: str | None) -> float | None:
    """A gross weight in kilograms.

    Digit grouping is stripped before parsing: the bundle writes the same
    weight as both "243588" and "243,588", which is a formatting difference
    and not a defect.
    """
    if value is None:
        return None
    multiplier = 1.0
    for pattern, factor in _UNITS:
        if pattern.search(value):
            multiplier = factor
            break
    digits = re.search(r"\d[\d,. ]*", value)
    if not digits:
        return None
    number = digits.group().strip().rstrip(".,")
    # Commas and spaces are digit grouping; a trailing ".5" is a decimal.
    number = number.replace(",", "").replace(" ", "")
    try:
        return float(number) * multiplier
    except ValueError:  # pragma: no cover - defensive
        return None
