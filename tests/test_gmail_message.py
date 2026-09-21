"""The round trip: an EmailRecord into Gmail and back out unchanged."""
import pytest

from tests.gmail_fake import as_message
from vsmail.documents import role_from_path
from vsmail.gmail.message import (
    ID_HEADER,
    attachment_uri,
    build_mime,
    encode,
    parse_attachment_uri,
    spread_dates,
    to_record,
)
from vsmail.models import EmailRecord

_RECORD = EmailRecord(
    email_id="email_004",
    sender="docs@vitalsolutions.sg",
    subject="REQUEST BL DRAFT _ PO 26067",
    body="Hi Mitchelle,\n\nAttached are the SI and draft BL for OC 5ALT-01226.",
    attachments=("attachments/email_004_SI.txt", "attachments/email_004_BL.txt"),
)
_FILES = [("email_004_SI.txt", b"SHIPPING INSTRUCTION"), ("email_004_BL.txt", b"BILL OF LADING")]


def _round_trip(record=_RECORD, files=_FILES):
    return to_record(as_message(build_mime(record, files, to="ops@example.test")))


def test_the_bundle_id_survives():
    """The one that matters. The submission is keyed by these ids, so losing
    this header would silently produce 520 unrecognisable entries."""
    assert _round_trip().email_id == "email_004"


def test_the_original_sender_survives():
    """Only insertion can preserve this; genuine delivery would rewrite it."""
    assert _round_trip().sender == "docs@vitalsolutions.sg"


def test_subject_and_body_survive():
    result = _round_trip()
    assert result.subject == "REQUEST BL DRAFT _ PO 26067"
    assert "Attached are the SI and draft BL" in result.body


def test_attachments_come_back_as_fetchable_references():
    result = _round_trip()
    assert len(result.attachments) == 2
    for uri in result.attachments:
        message_id, attachment_id, name = parse_attachment_uri(uri)
        assert message_id and attachment_id and name.endswith(".txt")


def test_the_si_and_bl_slots_still_resolve():
    """Downstream reads the role off the filename, so the reference has to
    keep ending in it."""
    result = _round_trip()
    assert result.attachment_for("SI") is not None
    assert result.attachment_for("BL") is not None
    assert role_from_path(result.attachment_for("SI")) == "SI"


def test_an_email_with_no_attachments_round_trips():
    plain = EmailRecord("email_002", "a@b.test", "Query on invoice", "Is THC included?")
    result = _round_trip(plain, [])
    assert result.email_id == "email_002"
    assert result.attachments == ()
    assert "THC" in result.body


def test_a_delivered_message_gets_an_id_from_gmail():
    """A genuinely delivered email carries no seeded header. It still has to
    produce a usable record so live mail flows through the same pipeline."""
    message = as_message(build_mime(_RECORD, [], to="ops@example.test"), "ABC123")
    message["payload"]["headers"] = [
        h for h in message["payload"]["headers"] if h["name"] != ID_HEADER
    ]
    result = to_record(message)
    assert result.email_id == "gmail_ABC123"
    assert result.sender == "docs@vitalsolutions.sg"


def test_encoding_is_base64url():
    raw = encode(build_mime(_RECORD, _FILES, to="ops@example.test"))
    assert "+" not in raw and "/" not in raw, "must be url-safe for the API"


def test_dates_are_distinct_and_ordered():
    """Without this every seeded message lands in the same second."""
    dates = spread_dates(520)
    assert len(set(dates)) == 520
    assert dates == sorted(dates)


def test_a_bad_attachment_reference_is_refused():
    with pytest.raises(ValueError, match="not a Gmail attachment"):
        parse_attachment_uri("attachments/email_004_SI.txt")


def test_uri_round_trips():
    uri = attachment_uri("M", "A", "email_004_SI.txt")
    assert parse_attachment_uri(uri) == ("M", "A", "email_004_SI.txt")


def test_uri_quotes_a_customer_filename_without_losing_it():
    uri = attachment_uri("M", "A", "Draft B/L #2.pdf")
    assert "%2F" in uri and "%23" in uri
    assert parse_attachment_uri(uri) == ("M", "A", "Draft B/L #2.pdf")


def test_a_small_inline_attachment_is_not_dropped():
    import base64

    message = as_message(
        build_mime(
            _RECORD,
            [("Shipping Instructions.txt", b"SHIPPING INSTRUCTION")],
            to="ops@example.test",
        )
    )
    attachment = message["payload"]["parts"][1]
    attachment["body"].pop("attachmentId")
    attachment["body"]["data"] = base64.urlsafe_b64encode(
        b"SHIPPING INSTRUCTION"
    ).decode()

    result = to_record(message)

    assert len(result.attachments) == 1
    assert parse_attachment_uri(result.attachments[0])[1].startswith("inline-")
    assert result.attachment_for("SI") is not None


def test_an_empty_named_attachment_is_still_visible():
    message = as_message(
        build_mime(_RECORD, [("Draft BL.pdf", b"")], to="ops@example.test")
    )
    attachment = message["payload"]["parts"][1]
    attachment["body"] = {"size": 0, "data": ""}

    result = to_record(message)

    assert len(result.attachments) == 1
    assert result.attachment_for("BL") is not None


def test_unpadded_base64url_body_is_decoded():
    import base64

    message = as_message(build_mime(_RECORD, [], to="ops@example.test"))
    encoded = base64.urlsafe_b64encode(b"a body requiring padding").decode().rstrip("=")
    message["payload"]["body"]["data"] = encoded

    assert to_record(message).body == "a body requiring padding"
