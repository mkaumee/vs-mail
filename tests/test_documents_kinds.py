"""Rejecting a document that does not belong in the slot."""
import pytest

from vsmail.documents.kinds import DISQUALIFYING, detect_doc_kind


@pytest.mark.parametrize(
    "email_id,expected",
    [
        ("email_501", "commercial_invoice"),
        ("email_502", "packing_list"),
        ("email_503", "certificate_of_origin"),
        ("email_504", "packing_list"),
        ("email_505", "certificate_of_origin"),
    ],
)
def test_planted_wrong_documents_are_named(bundle, read_attachment, email_id, expected):
    path = bundle.get(email_id).attachment_for("BL")
    assert read_attachment(path).doc_kind == expected


def test_every_named_kind_is_disqualifying():
    assert DISQUALIFYING == {
        "commercial_invoice",
        "packing_list",
        "certificate_of_origin",
    }


def test_real_shipping_documents_are_not_flagged(bundle, read_attachment):
    """The other 245 readable attachments must all come back unflagged."""
    planted = {f"email_{n}" for n in range(501, 506)}
    for email in bundle.emails():
        if email.email_id in planted:
            continue
        for path in email.attachments:
            document = read_attachment(path)
            assert document.doc_kind is None, f"{path} was wrongly rejected"


def test_an_invoice_mentioning_a_bill_of_lading_is_still_an_invoice():
    # email_501 says "30 days from B/L date"; the heading must still win.
    text = "COMMERCIAL INVOICE\n\nTotal: USD 1\nPayment Terms: 30 days from B/L date"
    assert detect_doc_kind(text) == "commercial_invoice"


def test_a_scan_with_no_text_has_no_detectable_kind(read_attachment):
    document = read_attachment("attachments/email_512_SI.pdf")
    assert document.doc_kind is None


def test_a_mention_far_below_the_heading_is_ignored():
    text = "\n".join(["BILL OF LADING (DRAFT)"] + ["filler"] * 30 + ["PACKING LIST"])
    assert detect_doc_kind(text) is None


def test_a_disqualifying_document_is_caught_in_other_languages():
    """English-only was a fair bet against an English bundle and a poor one
    against a customer who attaches a 商业发票."""
    from vsmail.documents.kinds import detect_doc_kind

    cases = [
        ("商业发票", "commercial_invoice"),
        ("FACTURA COMERCIAL", "commercial_invoice"),
        ("HÓA ĐƠN THƯƠNG MẠI", "commercial_invoice"),
        ("装箱单", "packing_list"),
        ("PACKLISTE", "packing_list"),
        ("原产地证", "certificate_of_origin"),
        ("CERTIFICAT D'ORIGINE", "certificate_of_origin"),
        ("CERTIFICAT D\u2019ORIGINE", "certificate_of_origin"),
    ]
    for heading, expected in cases:
        assert detect_doc_kind(heading + "\nSeller: ACME\n") == expected, heading


def test_a_shipping_document_is_still_comparable_in_any_language():
    from vsmail.documents.kinds import detect_doc_kind

    assert detect_doc_kind("SHIPPING INSTRUCTION\nShipper: ACME") is None
    assert detect_doc_kind("BILL OF LADING INSTRUCTION\nShipper: ACME") is None
