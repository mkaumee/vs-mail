from vsmail.documents import read_document, role_from_path


def test_role_is_read_from_the_filename():
    assert role_from_path("attachments/email_004_SI.txt") == "SI"
    assert role_from_path("attachments/email_004_BL.txt") == "BL"
    assert role_from_path("attachments/whatever.txt") == "UNKNOWN"


def test_role_ignores_a_misleading_document_heading(read_attachment):
    # email_059_SI.pdf is titled "BILL OF LADING INSTRUCTION" but fills the
    # SI slot; the filename decides, not the heading.
    assert role_from_path("attachments/email_059_SI.pdf") == "SI"


def test_text_attachment_reads(read_attachment):
    document = read_attachment("attachments/email_004_SI.txt")
    assert document.readable
    assert document.role == "SI"
    assert document.text.startswith("SHIPPING INSTRUCTION")
    assert not document.images


def test_unsupported_format_reports_rather_than_raises():
    document = read_document("attachments/mystery.rtf", b"...")
    assert not document.readable
    assert "unsupported" in document.error
    assert document.is_empty
