"""PDF handling — the bundle plants one of each interesting case."""

import pytest


def test_text_layer_pdf_reads_as_text(read_attachment):
    document = read_attachment("attachments/email_059_SI.pdf")
    assert document.readable
    assert not document.images
    assert "BILL OF LADING INSTRUCTION" in document.text
    assert len(document.text) > 500


def test_image_only_pdf_comes_back_as_page_images(read_attachment):
    # emails 512-514 ship scans with no text layer at all.
    document = read_attachment("attachments/email_512_SI.pdf")
    assert document.readable
    assert document.text == ""
    assert len(document.images) == 1
    assert document.images[0].startswith(b"\x89PNG"), "pages must rasterize to PNG"
    assert not document.is_empty, "a scan still has content, just not text"


def test_pdfium_reads_text_when_pymupdf_rejects_the_stream(
    bundle, monkeypatch
):
    from vsmail.documents import pdf

    def reject(*args, **kwargs):
        raise RuntimeError("Failed to open stream")

    monkeypatch.setattr(pdf.pymupdf, "open", reject)
    data = bundle.read_bytes("attachments/email_059_SI.pdf")

    text, images = pdf.read_pdf(data)

    assert "BILL OF LADING INSTRUCTION" in text
    assert images == ()


def test_pdfium_rasterizes_a_scan_when_pymupdf_rejects_the_stream(
    bundle, monkeypatch
):
    from vsmail.documents import pdf

    def reject(*args, **kwargs):
        raise RuntimeError("Failed to open stream")

    monkeypatch.setattr(pdf.pymupdf, "open", reject)
    data = bundle.read_bytes("attachments/email_512_SI.pdf")

    text, images = pdf.read_pdf(data)

    assert text == ""
    assert len(images) == 1
    assert images[0].startswith(b"\x89PNG")


def test_corrupt_pdf_is_flagged_not_raised(read_attachment):
    # emails 511 and 515 ship a truncated BL.
    document = read_attachment("attachments/email_511_BL.pdf")
    assert not document.readable
    assert document.error
    assert document.is_empty


def test_the_other_corrupt_pdf_behaves_the_same(read_attachment):
    document = read_attachment("attachments/email_515_BL.pdf")
    assert not document.readable


def test_every_pdf_in_the_bundle_is_classified(bundle, read_attachment):
    """No PDF should raise; each is readable text, readable images, or flagged."""
    from vsmail.inbox import DEFAULT_SOURCE

    paths = sorted((DEFAULT_SOURCE / "attachments").glob("*.pdf"))
    assert len(paths) == 28

    text_layer = scans = corrupt = 0
    for path in paths:
        document = read_attachment(f"attachments/{path.name}")
        if not document.readable:
            corrupt += 1
        elif document.images:
            scans += 1
        else:
            text_layer += 1

    assert (text_layer, scans, corrupt) == (20, 6, 2)
