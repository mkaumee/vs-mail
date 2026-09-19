"""Aligning document labels onto the seven compared fields."""
import pytest

from vsmail.config import FIELDS
from vsmail.documents import read_document
from vsmail.fields import field_for_label, parse_fields


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Shipper", "shipper"),
        ("Shipper/Exporter", "shipper"),
        ("Shipper (Principal or Seller) (发货人)", "shipper"),
        ("Consignee (Non-Negotiable)", "consignee"),
        ("To the Order of", "consignee"),
        ("Notify", "notify_party"),
        ("NOTIFY PARTY", "notify_party"),
        ("Port of Loading (POL)", "port_of_loading"),
        ("Load Port", "port_of_loading"),
        ("POL", "port_of_loading"),
        ("Discharge Port", "port_of_discharge"),
        ("POD", "port_of_discharge"),
        ("Total Containers", "container_count"),
        ("No. of Containers or Packages", "container_count"),
        ("Gross Wt (kgs)", "gross_weight_kg"),
        ("Gross Weight毛重(KGS)", "gross_weight_kg"),
        ("TOTAL Gross Weight (KG)", "gross_weight_kg"),
    ],
)
def test_labels_map_to_their_field(label, expected):
    assert field_for_label(label) == expected


@pytest.mark.parametrize(
    "label",
    ["Vessel Name", "Booking Ref", "HS Code", "Freight", "Commodity", "Voyage"],
)
def test_unrelated_labels_map_to_nothing(label):
    assert field_for_label(label) is None


def test_intermediate_consignee_is_the_notify_party():
    """The label names both; it is the notify party, and order decides."""
    assert field_for_label("Notify Party/Intermediate Consignee") == "notify_party"


def test_packages_description_is_not_a_container_count():
    assert field_for_label("Kinds of Packages; Description of Goods") is None


def test_net_weight_is_not_the_gross_weight():
    assert field_for_label("NET WEIGHT") is None


def test_container_column_header_is_not_a_count():
    assert field_for_label("CONTAINER NO.") is None


def _fields(bundle, path):
    return parse_fields(read_document(path, bundle.read_bytes(path)).text)


def test_same_line_layout_parses(bundle):
    values = _fields(bundle, "attachments/email_004_SI.txt")
    assert values["consignee"] == "EAST BRIGHT FZ-LLC"
    assert values["port_of_loading"] == "NANTONG, CHINA (CNNTG)"
    assert values["container_count"] == "6 x 40'HC"
    assert values["gross_weight_kg"] == "131,058 KG"


def test_party_name_is_kept_without_its_address(bundle):
    """email_004's consignee differs while the address below is identical."""
    si = _fields(bundle, "attachments/email_004_SI.txt")
    bl = _fields(bundle, "attachments/email_004_BL.txt")
    assert si["consignee"] == "EAST BRIGHT FZ-LLC"
    assert bl["consignee"] == "UAB NOVAKOPA"
    assert "RAKEZ" not in (si["consignee"] or ""), "the address must be dropped"


def test_block_layout_pdf_parses(bundle):
    """PDFs put the label on its own line with the value beneath."""
    values = _fields(bundle, "attachments/email_059_SI.pdf")
    assert values["shipper"] == "APRIL FINE PAPER TRADING"
    assert values["consignee"] == "BALL & DOGGETT AUSTRALIA PTY LTD"
    assert values["port_of_loading"] == "BUATAN, INDONESIA"
    assert values["port_of_discharge"] == "FREMANTLE, AUSTRALIA"
    # These two come from the summary lines below the container table.
    assert values["container_count"] == "6 x 40'HC"
    assert values["gross_weight_kg"] == "131,322 KG"


def test_label_fused_onto_its_value_parses(bundle):
    """The BL writes 'Consignee (Non-Negotiable) BALL & DOGGETT ...' inline."""
    values = _fields(bundle, "attachments/email_059_BL.pdf")
    assert values["consignee"] == "BALL & DOGGETT AUSTRALIA PTY LTD"


def test_spreadsheet_and_word_pair_agree_on_the_party_name(bundle):
    si = _fields(bundle, "attachments/email_055_SI.xlsx")
    bl = _fields(bundle, "attachments/email_055_BL.docx")
    assert si["shipper"] == bl["shipper"] == "APRIL FINE PAPER TRADING"
    assert si["consignee"] == bl["consignee"] == "AL GURG STATIONERY LLC"


def test_a_blank_value_parses_as_missing(bundle):
    """emails 519 and 520 leave a required field empty in the SI."""
    assert _fields(bundle, "attachments/email_519_SI.txt")["shipper"] is None
    assert _fields(bundle, "attachments/email_519_SI.txt")["container_count"] is None
    assert _fields(bundle, "attachments/email_520_SI.txt")["consignee"] is None


def test_parse_always_returns_every_field(bundle):
    values = _fields(bundle, "attachments/email_004_SI.txt")
    assert list(values) == list(FIELDS)
