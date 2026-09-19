"""Word attachments — 8 files, each a draft BL.

Paragraphs carry the heading and reference numbers; the shipment fields sit
in a table whose labels are bilingual, so the reader walks the document body
in order rather than reading paragraphs and tables separately.
"""
from __future__ import annotations

import io

import docx
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from vsmail.documents.base import DocumentUnreadable
from vsmail.documents.tabular import flatten, render_row


def _blocks(document):
    """Yield paragraphs and tables in the order they appear in the document."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def read_docx(data: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentUnreadable(f"Word document could not be opened: {exc}") from exc

    lines: list[str] = []
    for block in _blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                lines.append(text)
            continue
        for row in block.rows:
            cells = [flatten(cell.text) for cell in row.cells]
            line = render_row(cells)
            if line:
                lines.append(line)

    text = "\n".join(lines).strip()
    if not text:
        raise DocumentUnreadable("Word document contains no readable content")
    return text
