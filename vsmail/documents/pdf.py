"""PDF attachments.

Most PDFs in the bundle carry a clean text layer. A handful are image-only
scans with no text at all, and two are corrupt. Each needs different
handling, and telling them apart is what decides between reading a document
and escalating it.
"""
from __future__ import annotations

import pymupdf

from vsmail.documents.base import DocumentUnreadable

#: Below this many characters a PDF is treated as having no text layer.
#: The image-only scans in this bundle yield exactly zero; real documents
#: yield hundreds. The gap is wide, so the threshold is not delicate.
MIN_TEXT_CHARS = 20

#: Rasterizing resolution for scans handed to a vision model. 200 keeps
#: small print legible without inflating the payload.
RASTER_DPI = 200


def read_pdf(data: bytes) -> tuple[str, tuple[bytes, ...]]:
    """Return the text layer, or rasterized pages when there is none.

    Raises `DocumentUnreadable` for a file PyMuPDF cannot open, or one that
    yields neither text nor pages.
    """
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentUnreadable(f"PDF could not be opened: {exc}") from exc

    with document:
        if document.page_count == 0:
            raise DocumentUnreadable("PDF contains no pages")

        text = "\n".join(page.get_text() for page in document).strip()
        if len(text) >= MIN_TEXT_CHARS:
            return text, ()

        # No usable text layer: hand back page images for a vision model.
        images = tuple(
            page.get_pixmap(dpi=RASTER_DPI).tobytes("png") for page in document
        )

    if not images:  # pragma: no cover - defensive
        raise DocumentUnreadable("PDF yielded neither text nor page images")
    return "", images
