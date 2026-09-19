"""Normalization — where false alarms are won or lost."""
import pytest

from vsmail.normalize import (
    normalize_container_count,
    normalize_name,
    normalize_port,
    normalize_weight_kg,
    port_code,
)


@pytest.mark.parametrize(
    "a,b",
    [
        ("22,000 KG", "22000 kgs"),
        ("243588", "243,588"),
        ("131,058 KG", "131058"),
        ("22 MT", "22000 KG"),
    ],
)
def test_equivalent_weights_normalize_alike(a, b):
    assert normalize_weight_kg(a) == normalize_weight_kg(b)


def test_different_weights_stay_different():
    assert normalize_weight_kg("21,114 KG") != normalize_weight_kg("23,114 KG")


def test_metric_tonnes_convert():
    assert normalize_weight_kg("22 MT") == 22000.0
    assert normalize_weight_kg("1.5 tonnes") == 1500.0


def test_container_count_is_the_leading_number():
    assert normalize_container_count("6 x 40'HC") == 6
    assert normalize_container_count("12 x 20'FCL") == 12
    assert normalize_container_count("3") == 3


def test_names_fold_case_and_punctuation():
    assert normalize_name("MAERSK LINE") == normalize_name("Maersk Line")
    assert normalize_name("KTP CO., LTD") == normalize_name("KTP CO LTD")
    assert normalize_name("KPP-ANTALIS (SINGAPORE)") == normalize_name("KPP ANTALIS SINGAPORE")


def test_legal_suffixes_are_kept():
    """Two entities that differ only by suffix are still two entities."""
    assert normalize_name("APRIL FINE PAPER TRADING") != normalize_name(
        "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE"
    )


def test_adding_a_port_code_is_not_a_change():
    assert normalize_port("NHAVA SHEVA, INDIA") == normalize_port("NHAVA SHEVA, INDIA (INNSA)")


def test_the_port_name_decides_not_the_code():
    """email_119 keeps the code MYPKG while changing the port itself."""
    assert normalize_port("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)") != normalize_port(
        "SINGAPORE, SINGAPORE (MYPKG)"
    )


def test_a_parenthetical_that_is_part_of_the_name_survives():
    assert "WESTPORT" in normalize_port("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)")


def test_port_code_is_readable_for_display():
    assert port_code("NANTONG, CHINA (CNNTG)") == "CNNTG"
    assert port_code("SINGAPORE") is None


def test_missing_values_stay_missing():
    assert normalize_name(None) is None
    assert normalize_port(None) is None
    assert normalize_weight_kg(None) is None
    assert normalize_container_count(None) is None


@pytest.mark.parametrize(
    "value",
    ["N/A", "n/a", "NA", "TBA", "TBD", "____MT", "_______ MTS", "??? MTS",
     "-", "---", "NONE", "NIL", "to be advised", "", "   ", None],
)
def test_placeholders_state_no_value(value):
    from vsmail.normalize import is_placeholder

    assert is_placeholder(value)


@pytest.mark.parametrize(
    "value",
    ["22,000 KG", "NANTONG, CHINA", "SINGAPORE", "NAGAPPA EXPORTS",
     "NIL PAPER CO LTD", "6 x 40'HC", "235,550 KG", "KTP CO., LTD"],
)
def test_real_values_are_not_placeholders(value):
    from vsmail.normalize import is_placeholder

    assert not is_placeholder(value)
