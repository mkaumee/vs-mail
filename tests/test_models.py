import json

from vsmail.inbox import DEFAULT_SOURCE
from vsmail.models import EmailRecord, Verdict, trim_body


def _record(email_id: str) -> EmailRecord:
    path = DEFAULT_SOURCE / "inbox" / f"{email_id}.json"
    return EmailRecord.from_json(json.loads(path.read_text()))


def test_attachment_slots_come_from_the_filename():
    record = _record("email_004")
    assert record.attachment_for("SI") == "attachments/email_004_SI.txt"
    assert record.attachment_for("BL") == "attachments/email_004_BL.txt"


def test_missing_slot_is_none():
    # email_507 ships an SI with no BL alongside it.
    record = _record("email_507")
    assert record.attachment_for("SI") is not None
    assert record.attachment_for("BL") is None


def test_natural_customer_filenames_fill_the_document_slots():
    record = EmailRecord(
        "gmail_x",
        "sender@example.test",
        "Please compare",
        "Attached are both documents.",
        ("Shipping Instructions.xlsx", "Draft Bill of Lading.pdf"),
    )

    assert record.attachment_for("SI") == "Shipping Instructions.xlsx"
    assert record.attachment_for("BL") == "Draft Bill of Lading.pdf"


def test_two_generic_documents_are_opened_in_attachment_order():
    record = EmailRecord(
        "gmail_x",
        "sender@example.test",
        "Please compare",
        "Attached are both documents.",
        ("Customer document.pdf", "Carrier document.pdf"),
    )

    assert record.attachment_for("SI") == "Customer document.pdf"
    assert record.attachment_for("BL") == "Carrier document.pdf"


def test_one_unidentified_file_is_not_claimed_as_both_documents():
    record = EmailRecord(
        "gmail_x",
        "sender@example.test",
        "Please compare",
        "See attachment.",
        ("document.pdf",),
    )

    assert record.attachment_for("SI") is None
    assert record.attachment_for("BL") is None


def test_trim_body_drops_the_signature_block():
    record = _record("email_004")
    assert "Attached are the SI and draft BL" in record.core_body
    assert "Best Regards" not in record.core_body
    assert "aprilasia.com" not in record.core_body


def test_trim_body_drops_the_external_mail_banner():
    # email_061 opens with a security banner that is not part of the request.
    record = _record("email_061")
    assert not record.core_body.startswith("WARNING")
    assert "Please assist to send the draft BL" in record.core_body


def test_trim_body_drops_quoted_reply_history():
    # email_002 carries a quoted earlier message after the separator.
    record = _record("email_002")
    assert "Query on invoice" in record.core_body
    assert "Hari Mardianto" not in record.core_body


def test_trim_body_survives_an_empty_body():
    assert trim_body("") == ""


def test_verdict_renders_the_submission_schema():
    entry = Verdict(
        email_id="email_004",
        category="BL_COMPARISON",
        status="MISMATCH",
        has_defect=True,
        defect_fields=["consignee", "notify_party"],
    ).to_submission_entry()
    assert set(entry) == {
        "category",
        "status",
        "review_reason",
        "has_defect",
        "defect_fields",
    }
    assert entry["review_reason"] is None
