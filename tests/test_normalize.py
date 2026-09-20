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


# -- found by the stress inbox -------------------------------------------
def test_a_unit_with_no_space_still_converts():
    """`\\b` needs a non-word character before the unit, and in "22MT" the
    character before M is "2". So the multiplier stayed at 1 and 22MT compared
    as 22 kg against 22,000 kg — a defect reported for a missing space."""
    from vsmail.normalize import normalize_weight_kg

    assert normalize_weight_kg("22MT") == 22000.0
    assert normalize_weight_kg("22 MT") == 22000.0
    assert normalize_weight_kg("1500KGS") == 1500.0


def test_a_unit_inside_a_longer_word_is_not_a_unit():
    """The boundary still has to hold in the other direction."""
    from vsmail.normalize import normalize_weight_kg

    assert normalize_weight_kg("22 MTX") == 22.0


def test_an_accent_is_not_a_different_company():
    """Keeping only [0-9A-Za-z] turned "CAFÉ" into "CAF", so any name that is
    not plain ASCII read as a different entity — and in this trade a great
    many are not."""
    from vsmail.normalize import normalize_name

    assert normalize_name("CAFÉ DO BRASIL LTDA") == normalize_name("CAFE DO BRASIL LTDA")
    assert normalize_name("MÜLLER GMBH") == normalize_name("MULLER GMBH")
    assert normalize_name("ØRSTED A/S") is not None


def test_a_non_latin_name_is_not_erased():
    """`\\w` is Unicode-aware, so a Chinese name survives rather than
    normalising down to nothing."""
    from vsmail.normalize import normalize_name

    assert normalize_name("上海紙業有限公司") == "上海紙業有限公司"


def test_accents_do_not_collapse_genuinely_different_names():
    from vsmail.normalize import normalize_name

    assert normalize_name("ACME PAPER LTD") != normalize_name("ACME PAPER FZE")


def test_a_port_code_in_square_brackets_is_still_a_code():
    from vsmail.normalize import normalize_port

    assert normalize_port("SINGAPORE [SGSIN]") == normalize_port("SINGAPORE")
    assert normalize_port("SINGAPORE (SGSIN)") == normalize_port("SINGAPORE")


def test_the_port_trap_survives_the_bracket_change():
    """The whole reason codes are ignored: email_119 carries (MYPKG) on both
    sides while the port itself changes."""
    from vsmail.normalize import normalize_port

    assert normalize_port("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)") != normalize_port(
        "SINGAPORE, SINGAPORE (MYPKG)"
    )


# -- other languages ------------------------------------------------------
def test_stroke_letters_fold_because_nfkd_will_not():
    """Ø and Đ are their own letters to Unicode, not O and D with marks, so
    decomposition leaves them alone. Both turn up in real party names."""
    from vsmail.normalize import normalize_name

    assert normalize_name("ØRSTED PAPER A/S") == normalize_name("ORSTED PAPER A/S")
    assert normalize_name("CÔNG TY GIẤY ĐÀ NẴNG") == normalize_name("CONG TY GIAY DA NANG")
    assert normalize_name("MÆRSK PAPER") == normalize_name("MAERSK PAPER")


def test_full_width_latin_folds():
    from vsmail.normalize import normalize_name

    assert normalize_name("ＡＣＭＥ ＰＡＰＥＲ ＬＴＤ") == normalize_name("ACME PAPER LTD")


def test_a_space_between_cjk_characters_is_layout_not_a_word_break():
    from vsmail.normalize import normalize_name

    assert normalize_name("上海 紙業有限公司") == normalize_name("上海紙業有限公司")


def test_a_space_between_latin_words_is_still_a_word_break():
    from vsmail.normalize import normalize_name

    assert normalize_name("ACME PAPER") != normalize_name("ACMEPAPER")


def test_traditional_and_simplified_stay_different():
    """Deliberate. Folding them needs a real conversion table, and getting it
    subtly wrong would merge two different companies silently. The model's
    equivalence judge can raise it as possibly-the-same instead."""
    from vsmail.normalize import normalize_name

    assert normalize_name("上海紙業有限公司") != normalize_name("上海纸业有限公司")
