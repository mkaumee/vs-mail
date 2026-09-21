"""PDF attachments.

Most PDFs in the bundle carry a clean text layer. A handful are image-only
scans with no text at all, and two are corrupt. Each needs different
handling, and telling them apart is what decides between reading a document
and escalating it.
"""
from __future__ import annotations

import io

import pymupdf
import pypdfium2 as pdfium

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

    PyMuPDF is the fast primary reader. PDFium is the fallback because some
    valid PDFs render in a browser but PyMuPDF rejects their stream layout.
    Raises `DocumentUnreadable` only when neither engine can read the file.
    """
    try:
        return _read_with_pymupdf(data)
    except Exception as primary_error:
        try:
            return _read_with_pdfium(data)
        except Exception as fallback_error:
            raise DocumentUnreadable(
                "automatic PDF reading failed "
                f"(PyMuPDF: {primary_error}; PDFium: {fallback_error})"
            ) from fallback_error


def _read_with_pymupdf(data: bytes) -> tuple[str, tuple[bytes, ...]]:
    """Read with the primary parser."""
    document = pymupdf.open(stream=data, filetype="pdf")

    with document:
        if document.page_count == 0:
            raise ValueError("PDF contains no pages")

        text = "\n".join(page.get_text() for page in document).strip()
        if len(text) >= MIN_TEXT_CHARS:
            return text, ()

        # No usable text layer: hand back page images for a vision model.
        images = tuple(
            page.get_pixmap(dpi=RASTER_DPI).tobytes("png") for page in document
        )

    if not images:  # pragma: no cover - defensive
        raise ValueError("PDF yielded neither text nor page images")
    return "", images


def _read_with_pdfium(data: bytes) -> tuple[str, tuple[bytes, ...]]:
    """Read with browser-grade PDFium when the primary parser rejects a PDF."""
    with pdfium.PdfDocument(data) as document:
        if len(document) == 0:
            raise ValueError("PDF contains no pages")

        chunks: list[str] = []
        for index in range(len(document)):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    chunks.append(text_page.get_text_bounded())
                finally:
                    text_page.close()
            finally:
                page.close()

        text = "\n".join(chunks).replace("\r\n", "\n").strip()
        if len(text) >= MIN_TEXT_CHARS:
            return text, ()

        images: list[bytes] = []
        for index in range(len(document)):
            page = document[index]
            try:
                bitmap = page.render(scale=RASTER_DPI / 72)
                try:
                    image = bitmap.to_pil()
                    try:
                        output = io.BytesIO()
                        image.save(output, format="PNG")
                        images.append(output.getvalue())
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()

    if not images:  # pragma: no cover - defensive
        raise ValueError("PDF yielded neither text nor page images")
    return "", tuple(images)
