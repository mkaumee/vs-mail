"""Shared rendering for the table-shaped formats.

The spreadsheet and Word attachments are both label/value tables. Rendering
a two-cell row as ``label: value`` makes them read like the plain-text
documents, so a single extraction prompt covers all four formats instead of
one per format.
"""
from __future__ import annotations


def render_row(cells: list[str]) -> str:
    """Render one table row as a line of text."""
    cells = [cell.strip() for cell in cells]
    cells = [cell for cell in cells if cell]
    if not cells:
        return ""
    if len(cells) == 2:
        return f"{cells[0]}: {cells[1]}"
    return " | ".join(cells)


def flatten(value: str) -> str:
    """Collapse a multi-line cell onto one line.

    Addresses arrive split across lines inside a single cell. The plain-text
    documents separate those same parts with semicolons, so matching that
    keeps one record on one line.
    """
    parts = [part.strip() for part in value.splitlines()]
    return "; ".join(part for part in parts if part)
