"""Spreadsheet and Word attachments."""
import pytest

from vsmail.documents.tabular import flatten, render_row


def test_two_cell_rows_render_as_label_and_value():
    assert render_row(["Load Port", "SINGAPORE"]) == "Load Port: SINGAPORE"


def test_wider_rows_fall_back_to_a_pipe_join():
    assert render_row(["a", "b", "c"]) == "a | b | c"


def test_blank_rows_render_as_nothing():
    assert render_row(["", "  "]) == ""


def test_flatten_joins_a_multiline_cell_with_semicolons():
    assert flatten("ACME LTD\nP.O. BOX 1\nDUBAI") == "ACME LTD; P.O. BOX 1; DUBAI"


def test_xlsx_reads_as_label_value_lines(read_attachment):
    document = read_attachment("attachments/email_055_SI.xlsx")
    assert document.readable
    assert not document.images
    assert "Load Port: SINGAPORE" in document.text
    assert "Container Count: 12 x 20'FCL" in document.text


def test_docx_reads_paragraphs_and_table_in_order(read_attachment):
    document = read_attachment("attachments/email_055_BL.docx")
    assert document.readable
    # The heading is a paragraph and precedes the field table.
    assert document.text.startswith("BILL OF LADING (DRAFT)")
    assert "PORT OF LOADING (装货港): SINGAPORE" in document.text


def test_docx_address_lines_stay_on_one_row(read_attachment):
    document = read_attachment("attachments/email_055_BL.docx")
    consignee = [
        line for line in document.text.splitlines() if line.startswith("Consignee")
    ]
    assert len(consignee) == 1
    assert "AL GURG STATIONERY LLC" in consignee[0]
    assert "DUBAI" in consignee[0], "the address must not be split onto its own line"


@pytest.mark.parametrize("suffix,expected", [(".xlsx", 22), (".docx", 8)])
def test_every_tabular_attachment_reads(read_attachment, suffix, expected):
    from vsmail.inbox import DEFAULT_SOURCE

    paths = sorted((DEFAULT_SOURCE / "attachments").glob(f"*{suffix}"))
    assert len(paths) == expected
    for path in paths:
        document = read_attachment(f"attachments/{path.name}")
        assert document.readable, f"{path.name} should parse"
        assert document.text.strip(), f"{path.name} produced no text"
