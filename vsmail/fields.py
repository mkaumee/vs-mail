"""Mapping document labels onto the seven compared fields.

The SI and the BL name the same field differently — "Port of Loading" against
"Load Port", "Total Containers" against "No. of Containers" — so alignment is
by meaning, not by header text. Across the bundle these seven fields appear
under 68 distinct labels, several of them bilingual.

Two labels are traps and are denied explicitly:

* "Notify Party/Intermediate Consignee" reads as both a notify party and a
  consignee. It is the notify party, so that rule is tested first.
* "Kinds of Packages; Description of Goods" reads as a container count
  because of the word *packages*. It is a goods description.
* "NET WEIGHT" is not the gross weight.

Documents come in two layouts. The plain-text, spreadsheet and Word files
put the value on the same line as its label. The PDFs use a block layout,
with the label on its own line and the value beneath, and sometimes fuse the
two together with no separator at all.
"""
from __future__ import annotations

import re

from vsmail.config import FIELDS
from vsmail.normalize import is_placeholder

#: (field, deny, allow) tried in order; the first rule that matches a label wins.
_RULES: tuple[tuple[str, str | None, str], ...] = (
    ("gross_weight_kg", r"net\s*w", r"gross\s*w|毛重"),
    ("notify_party", None, r"notify"),
    ("consignee", None, r"consignee|to\s+the\s+order\s+of"),
    ("shipper", None, r"shipper|exporter"),
    ("port_of_loading", None, r"port\s*of\s*loading|load\s*port|\bPOL\b"),
    ("port_of_discharge", None, r"port\s*of\s*discharge|discharge\s*port|\bPOD\b"),
    ("container_count", r"description|kinds\s+of\s+packages|container\s*no\.?$", r"container"),
)

_COMPILED = tuple(
    (field, re.compile(deny, re.I) if deny else None, re.compile(allow, re.I))
    for field, deny, allow in _RULES
)

#: Party names are followed by their address, separated by a pipe or semicolon
#: once a table cell has been flattened onto one line.
_PARTY_FIELDS = frozenset({"shipper", "consignee", "notify_party"})

#: `label: value`, used by the text, spreadsheet and Word documents.
_LABELLED = re.compile(r"^\s*([^:]{2,70}?)\s*:\s*(.*)$")

#: Complete labels as the PDFs write them, for the block layout where there is
#: no colon to split on. Each alternation is ordered longest first so the whole
#: label is consumed: matching only the keyword in "Notify Party" would leave
#: "Party" behind and read it as the value.
_BLOCK_LABELS: tuple[tuple[str, str], ...] = (
    ("notify_party", r"notify\s*party\s*/\s*intermediate\s*consignee|notify\s*party|notify"),
    ("consignee", r"consignee\s*\(non-negotiable\)|to\s*the\s*order\s*of|consignee"),
    ("shipper", r"shipper\s*\(principal\s*or\s*seller\)|shipper\s*/\s*exporter|shipper|exporter"),
    ("port_of_loading", r"port\s*of\s*loading\s*\(pol\)|port\s*of\s*loading|load\s*port|pol"),
    ("port_of_discharge", r"port\s*of\s*discharge\s*\(pod\)|port\s*of\s*discharge|discharge\s*port|pod"),
    ("container_count", r"no\.?\s*of\s*containers\s*or\s*packages|no\.?\s*of\s*containers|total\s*containers|container\s*count"),
    ("gross_weight_kg", r"total\s*gross\s*w(?:eight|t)|gross\s*weight|gross\s*wt"),
)

#: Anchored, with any trailing bilingual or unit parenthetical absorbed into
#: the label rather than left to contaminate the value.
_BLOCK_COMPILED = tuple(
    (field, re.compile(rf"^(?:{alternation})\b(?:\s*\([^)]*\))*", re.I))
    for field, alternation in _BLOCK_LABELS
)


def field_for_label(label: str) -> str | None:
    """The compared field a document label refers to, if any."""
    for field, deny, allow in _COMPILED:
        if deny is not None and deny.search(label):
            continue
        if allow.search(label):
            return field
    return None


def _clean(field: str, value: str) -> str:
    """Tidy a raw value, returning "" for anything that states no value.

    A document writing "N/A" or "____MT" has left the field blank. Reading
    that as a value would compare it against the other document and report a
    defect, when the right answer is to escalate for review.
    """
    if is_placeholder(value):
        return ""
    value = value.strip().strip("|;,").strip()
    if field in _PARTY_FIELDS:
        # Keep the party name, drop the address that follows it. In email_004
        # the consignee name differs between documents while the address below
        # is identical, so folding them together would hide the defect.
        value = re.split(r"\s*[|;]\s*", value)[0].strip()
    return value


def parse_fields(text: str) -> dict[str, str | None]:
    """Pull the seven fields out of a document's text.

    Runs the same-line layout first, then fills anything still missing from
    the block layout, so one parser covers every format in the bundle.
    """
    found: dict[str, str] = {}
    lines = [line.rstrip() for line in text.splitlines()]

    for line in lines:
        match = _LABELLED.match(line)
        if not match:
            continue
        label, value = match.group(1), match.group(2).strip()
        if not value:
            continue
        field = field_for_label(label)
        if field and field not in found:
            cleaned = _clean(field, value)
            if cleaned:
                found[field] = cleaned

    _parse_blocks(lines, found)
    return {field: found.get(field) for field in FIELDS}


def _parse_blocks(lines: list[str], found: dict[str, str]) -> None:
    """Fill remaining fields from the PDFs' block layout.

    A label sits on its own line with the value beneath it, or is fused onto
    the front of the value with no separator. Only fields still missing are
    filled, so a table's column headers cannot overwrite a real value.
    """
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or ":" in stripped:
            continue

        for field, pattern in _BLOCK_COMPILED:
            if field in found:
                continue
            match = pattern.match(stripped)
            if not match:
                continue

            # The value either follows the label on the same line, as in
            # "Consignee (Non-Negotiable) ACME LTD", or sits on the next one.
            value = stripped[match.end():].strip()
            if not value:
                value = next(
                    (nxt.strip() for nxt in lines[index + 1:] if nxt.strip()), ""
                )
            cleaned = _clean(field, value)
            if cleaned:
                found[field] = cleaned
            break
