"""The deterministic provider — the offline baseline the model is measured against."""
import collections

import pytest

from vsmail.llm.mock import MockProvider, classify_text


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Please assist to send the draft BL for SIN1 for checking asap.", "SI_REQUEST"),
        ("Attached are the SI and draft BL for OC 1. Please check and confirm.", "BL_COMPARISON"),
        ("Attached SI and draft BL for X for checking (the BL file will not open).", "BL_COMPARISON"),
        ("Pls assist to check the draft BL against the SI and revert.", "BL_COMPARISON"),
        ("Please compare the SI and draft BL for X and confirm.", "BL_COMPARISON"),
        ("Query on invoice 525: is the THC / local charge included?", "INVOICE_QUERY"),
        ("Please find the D&D / detention charges for X.", "INVOICE_QUERY"),
        ("LIMITED TIME OFFER! Get 90% off. Buy now before midnight.", "SPAM"),
        ("Your mailbox has exceeded its storage limit. Verify your account.", "SPAM"),
        ("Kindly find the daily berthing report attached.", "GENERAL"),
    ],
)
def test_bodies_classify_by_their_request(body, expected):
    assert classify_text(body).category == expected


def test_send_me_a_draft_is_not_a_comparison_request():
    """The decisive difference: 'send me X' against 'compare X with Y'."""
    send = "Please assist to send the draft BL for SIN832764835 for checking asap."
    compare = "Please compare the SI and draft BL for 070500263211 and confirm."
    assert classify_text(send).category == "SI_REQUEST"
    assert classify_text(compare).category == "BL_COMPARISON"


def test_naming_a_wrong_attachment_does_not_divert_the_request():
    """emails 501-505 mention an invoice but are still comparison requests."""
    body = (
        "Please find attached the SI and the Commercial Invoice for I009004365. "
        "Kindly confirm the BL is in order."
    )
    assert classify_text(body).category == "BL_COMPARISON"


async def test_every_email_in_the_bundle_is_classified(bundle):
    provider = MockProvider()
    counts = collections.Counter()
    for email in bundle.emails():
        result = await provider.classify(email)
        counts[result.category] += 1
    assert sum(counts.values()) == 520
    assert set(counts) == {
        "BL_COMPARISON",
        "SI_REQUEST",
        "INVOICE_QUERY",
        "GENERAL",
        "SPAM",
    }


async def test_comparison_requests_line_up_with_the_attachments(bundle):
    """Every email carrying attachments is a comparison request, and the only
    ones without are the three whose attachments were dropped in transit."""
    provider = MockProvider()
    without_attachments = []
    for email in bundle.emails():
        result = await provider.classify(email)
        is_comparison = result.category == "BL_COMPARISON"
        if is_comparison and not email.attachments:
            without_attachments.append(email.email_id)
        elif email.attachments:
            assert is_comparison, f"{email.email_id} has attachments but was not a comparison"
    assert without_attachments == ["email_506", "email_508", "email_510"]


async def test_extraction_reads_both_documents(bundle):
    from vsmail.documents import read_document

    provider = MockProvider()
    email = bundle.get("email_004")
    si_path, bl_path = email.attachment_for("SI"), email.attachment_for("BL")
    extraction = await provider.extract(
        read_document(si_path, bundle.read_bytes(si_path)),
        read_document(bl_path, bundle.read_bytes(bl_path)),
    )
    assert extraction.si["consignee"] == "EAST BRIGHT FZ-LLC"
    assert extraction.bl["consignee"] == "UAB NOVAKOPA"
    assert extraction.si["shipper"] == extraction.bl["shipper"]
