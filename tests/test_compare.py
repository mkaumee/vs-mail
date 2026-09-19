"""Field comparison and the escalation order."""
import pytest

from vsmail.compare import compare_field, decide
from vsmail.models import Document, EmailRecord, Extraction

_GOOD = {
    "shipper": "ACME LTD",
    "consignee": "BUYER LTD",
    "notify_party": "BUYER LTD",
    "port_of_loading": "SINGAPORE",
    "port_of_discharge": "KARACHI, PAKISTAN",
    "container_count": "6 x 40'HC",
    "gross_weight_kg": "22,000 KG",
}


def _email(email_id="email_x", attachments=("a/x_SI.txt", "a/x_BL.txt")):
    return EmailRecord(email_id, "s@x", "subject", "body", tuple(attachments))


def _doc(role, **kwargs):
    return Document(path=f"a/x_{role}.txt", role=role, text="t", **kwargs)


def _extraction(**overrides):
    bl = dict(_GOOD) | overrides
    return Extraction(si=dict(_GOOD), bl=bl)


@pytest.mark.parametrize(
    "field,si,bl",
    [
        ("gross_weight_kg", "22,000 KG", "22000 kgs"),
        ("consignee", "KTP CO., LTD", "KTP CO LTD"),
        ("port_of_loading", "NHAVA SHEVA, INDIA", "NHAVA SHEVA, INDIA (INNSA)"),
        ("container_count", "6 x 40'HC", "6 x 20'GP"),
    ],
)
def test_formatting_differences_are_not_defects(field, si, bl):
    result = compare_field(field, si, bl)
    assert result.equal
    assert result.differs_on_paper
    assert result.note, "an equal-but-differently-written pair must explain itself"


@pytest.mark.parametrize(
    "field,si,bl",
    [
        ("gross_weight_kg", "21,114 KG", "23,114 KG"),
        ("consignee", "EAST BRIGHT FZ-LLC", "UAB NOVAKOPA"),
        ("port_of_loading", "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)", "SINGAPORE, SINGAPORE (MYPKG)"),
        ("container_count", "6 x 20'GP", "5 x 20'GP"),
    ],
)
def test_real_differences_are_defects(field, si, bl):
    assert not compare_field(field, si, bl).equal


def test_identical_values_need_no_explanation():
    result = compare_field("shipper", "ACME LTD", "ACME LTD")
    assert result.equal and result.note is None


def test_a_non_comparison_email_is_left_alone():
    verdict = decide(_email(), "INVOICE_QUERY", None, None, None)
    assert (verdict.status, verdict.review_reason, verdict.has_defect) == ("OK", None, False)


def test_matching_documents_pass():
    verdict = decide(_email(), "BL_COMPARISON", _doc("SI"), _doc("BL"), _extraction())
    assert verdict.status == "OK"
    assert verdict.defect_fields == []


def test_a_single_differing_field_is_reported_alone():
    verdict = decide(
        _email(), "BL_COMPARISON", _doc("SI"), _doc("BL"), _extraction(container_count="4")
    )
    assert verdict.status == "MISMATCH"
    assert verdict.defect_fields == ["container_count"]
    assert verdict.has_defect


def test_a_missing_document_is_reported_as_missing():
    verdict = decide(_email(), "BL_COMPARISON", _doc("SI"), None, None)
    assert verdict.review_reason == "missing_attachment"


def test_an_unreadable_document_is_reported_as_unreadable():
    bl = Document(path="a/x_BL.pdf", role="BL", readable=False, error="boom")
    verdict = decide(_email(), "BL_COMPARISON", _doc("SI"), bl, None)
    assert verdict.review_reason == "unreadable"


def test_a_wrong_document_is_reported_as_wrong():
    bl = _doc("BL", doc_kind="commercial_invoice")
    verdict = decide(_email(), "BL_COMPARISON", _doc("SI"), bl, None)
    assert verdict.review_reason == "wrong_doc_type"


def test_a_blank_field_is_reported_as_missing_value():
    verdict = decide(
        _email(), "BL_COMPARISON", _doc("SI"), _doc("BL"), _extraction(consignee=None)
    )
    assert verdict.review_reason == "missing_value"


def test_a_missing_document_outranks_an_unreadable_one():
    """The first thing that went wrong is what gets reported."""
    bl = Document(path="a/x_BL.pdf", role="BL", readable=False, error="boom")
    assert decide(_email(), "BL_COMPARISON", None, bl, None).review_reason == "missing_attachment"


def test_a_wrong_document_outranks_its_missing_values():
    bl = _doc("BL", doc_kind="packing_list")
    verdict = decide(_email(), "BL_COMPARISON", _doc("SI"), bl, Extraction(si={}, bl={}))
    assert verdict.review_reason == "wrong_doc_type"
