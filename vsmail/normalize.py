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
import unicodedata

#: Text that fills a field without stating a value. A document writing "N/A",
#: "TBA" or "____MT" has left the field blank, and treating any of those as a
#: value turns a missing entry into a reported defect — a false alarm, and the
#: precise failure this system is scored on avoiding. The correct outcome is
#: to escalate the email for review instead.
_PLACEHOLDER = re.compile(
    r"^(?:"
    r"[\s_\-.?*]+"
    r"|(?:n\.?/?a|tba|tbd|tbc|none|nil|pending|unknown"
    r"|to\s+be\s+(?:advised|confirmed|determined))"
    r")"
    r"[\s_\-.?*]*"
    r"(?:kgs?|mts?|tons?|tonnes?)?"
    r"[\s_\-.?*]*$",
    re.I,
)


def is_placeholder(value: str | None) -> bool:
    """True when a field states no usable value.

    Covers an absent value, an empty one, and one filled in with text that
    only stands in for a value.
    """
    if value is None:
        return True
    stripped = value.strip()
    return not stripped or bool(_PLACEHOLDER.match(stripped))


#: A space sitting between two CJK characters. Removed; see `normalize_name`.
#: Traditional against Simplified (紙業 / 纸业) is deliberately *not* folded.
#: Mapping between them needs a real conversion table, and getting it subtly
#: wrong would silently merge two different companies. Left as a difference,
#: which the model's equivalence judge (`vsmail/equivalence.py`) can raise as
#: possibly-the-same for a person to settle — which is what that exists for.
_CJK_SPACE = re.compile(
    r"(?<=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])"
    r"\s+"
    r"(?=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])"
)

#: A UN/LOCODE or similar code in trailing brackets, either style.
_PARENTHETICAL = re.compile(r"[(\[]([^)\]]*)[)\]]")

#: Weight units, as a multiplier into kilograms.
#:
#: Bounded by letters rather than `\b`. A word boundary needs a non-word
#: character before the unit, and in "22MT" the character before M is "2" —
#: so `\bMT\b` never matched, the multiplier stayed at 1, and 22MT compared
#: as 22 kg against 22,000 kg. A real defect reported for a missing space.
_UNITS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"(?<![A-Za-z])(?:MT|M/?TONS?|METRIC\s*TONS?|TONNES?)(?![A-Za-z])", re.I), 1000.0),
    (re.compile(r"(?<![A-Za-z])(?:KGS?|KILOS?|KILOGRAMS?)(?![A-Za-z])", re.I), 1.0),
)


#: Letters NFKD will not decompose, because the mark is part of the letter
#: rather than an accent on it. Ø is not O-with-a-stroke to Unicode, it is its
#: own letter — so "ØRSTED" would keep the Ø and never match "ORSTED", and
#: Vietnamese "ĐƠN" would never match "DON". Both spellings turn up in real
#: party names, so they are mapped by hand.
_STROKED = str.maketrans({
    "Ø": "O", "ø": "o", "Đ": "D", "đ": "d", "Ð": "D", "ð": "d",
    "Ł": "L", "ł": "l", "Ħ": "H", "ħ": "h", "Ŧ": "T", "ŧ": "t",
    "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "ß": "ss", "Þ": "TH", "þ": "th",
})


def fold_accents(text: str) -> str:
    """Strip accents and stroke marks, leaving the base letters.

    Shared with `vsmail.documents.kinds`, so a document title and a party name
    are folded the same way and a pattern only needs writing once.
    """
    decomposed = unicodedata.normalize("NFKD", text.translate(_STROKED))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_name(value: str | None) -> str | None:
    """Fold case, accents, punctuation and spacing on a party or place name.

    Punctuation becomes a space rather than vanishing, so "KPP-ANTALIS" and
    "KPP ANTALIS" agree while distinct words never run together.

    Accents are folded rather than destroyed. The old rule kept only
    `[0-9A-Za-z]`, so "CAFÉ DO BRASIL" became "CAF DO BRASIL" and read as a
    different company from "CAFE DO BRASIL" — a false defect on any name that
    is not plain ASCII, which in this trade is a great many of them. Decompose
    first and drop the combining mark, and É becomes E.

    Non-Latin scripts survive too: `\w` is Unicode-aware, so a Chinese or
    Cyrillic name is kept rather than erased down to nothing.
    """
    if value is None:
        return None
    folded = re.sub(r"(?:[^\w]|_)+", " ", fold_accents(value)).strip().upper()
    collapsed = re.sub(r"\s+", " ", folded)
    # A space between two CJK characters is layout, not a word break — those
    # scripts do not separate words with spaces, so "上海 紙業" and "上海紙業"
    # are the same name typed two ways. Only between CJK: a space between
    # Latin words is still a word break.
    return re.sub(_CJK_SPACE, "", collapsed) or None


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
    # of the port's name, and drops only a trailing all-caps code. Square
    # brackets count: a code is a code whichever way it was typed.
    without_code = re.sub(
        r"[(\[]\s*[A-Z]{5}\s*[)\]]\s*$", "", value.strip()
    )
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
