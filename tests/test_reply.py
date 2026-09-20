"""The reply a checker would otherwise type.

The emails these go to are real customers, so most of what is pinned here is
about what the system must *not* say: no discrepancy announced without naming
it, no value paraphrased, no confidence the run did not actually have.
"""
import pytest

from vsmail.reply import ROLE_ADDRESSES, compose
from vsmail.results import Result


def make(**kw) -> Result:
    base = dict(
        email_id="email_x",
        category="BL_COMPARISON",
        status="OK",
        subject="TO CONFIRM DOCS _ 5RFR-36884",
        sender="hari_mardianto@aprilasia.com",
        fields=[],
    )
    return Result(**{**base, **kw})


def field(name, si, bl, equal=False, note=None):
    return {"field": name, "si": si, "bl": bl, "equal": equal, "note": note}


# -- who gets written to -------------------------------------------------
def test_only_comparison_requests_are_replied_to():
    """Triaging an invoice query into a lane is not grounds for writing to
    anybody."""
    for category in ("INVOICE_QUERY", "SI_REQUEST", "GENERAL", "SPAM"):
        assert compose(make(category=category)) is None


def test_a_person_is_greeted_by_name():
    assert compose(make()).body.startswith("Dear Hari,")


@pytest.mark.parametrize("local", ["docs", "exports", "sales", "info", "team"])
def test_a_role_address_is_not_given_a_first_name(local):
    """"Dear Docs," reads as a mail merge that guessed, which is exactly the
    impression this feature exists to avoid."""
    assert local in ROLE_ADDRESSES
    draft = compose(make(sender=f"{local}@vitalsolutions.sg"))
    assert draft.body.startswith("Dear Team,")


# -- the subject ---------------------------------------------------------
def test_the_reply_stays_in_the_thread():
    assert compose(make()).subject == "RE: TO CONFIRM DOCS _ 5RFR-36884"


def test_a_reply_to_a_reply_does_not_stack_prefixes():
    draft = compose(make(subject="RE: TO CONFIRM DOCS"))
    assert draft.subject == "RE: TO CONFIRM DOCS"


# -- a mismatch ----------------------------------------------------------
def test_a_mismatch_quotes_both_documents_verbatim():
    """Not normalized. The reader has to see what their own document says."""
    draft = compose(
        make(
            status="MISMATCH",
            defect_fields=["consignee"],
            fields=[field("consignee", "EAST BRIGHT FZ-LLC", "UAB NOVAKOPA")],
        )
    )
    assert draft.kind == "mismatch"
    assert 'SI: "EAST BRIGHT FZ-LLC"' in draft.body
    assert 'Draft BL: "UAB NOVAKOPA"' in draft.body
    assert "Kindly amend the draft" in draft.body


def test_only_the_defective_fields_are_raised():
    draft = compose(
        make(
            status="MISMATCH",
            defect_fields=["consignee"],
            fields=[
                field("consignee", "A LTD", "B LTD"),
                field("shipper", "SAME CO", "SAME CO", equal=True),
            ],
        )
    )
    assert "Consignee" in draft.body
    assert "SAME CO" not in draft.body


def test_a_mismatch_never_announces_discrepancies_and_lists_none():
    """Regression. A result without per-field detail produced "the following
    do not agree:" followed by a blank line — an email that must never reach
    a customer."""
    draft = compose(
        make(status="MISMATCH", defect_fields=["consignee", "gross_weight_kg"], fields=[])
    )
    assert "consignee" in draft.body
    assert "gross weight" in draft.body
    body = draft.body
    announce = body.index("do not agree:")
    ask = body.index("Kindly amend")
    assert body[announce:ask].strip().splitlines()[-1].strip()


# -- a blocked comparison ------------------------------------------------
@pytest.mark.parametrize(
    "reason,expected",
    [
        ("missing_attachment", "did not arrive"),
        ("unreadable", "will not open"),
        ("wrong_doc_type", "not the document it should be"),
    ],
)
def test_a_blocked_comparison_says_what_would_unblock_it(reason, expected):
    draft = compose(make(status="NEEDS_REVIEW", review_reason=reason))
    assert expected in draft.body
    assert "Could you resend" in draft.body


def test_a_blank_field_reads_as_blank():
    draft = compose(
        make(
            status="NEEDS_REVIEW",
            review_reason="missing_value",
            fields=[
                field("gross_weight_kg", None, "235,550 KG"),
                field("shipper", "A", "A", equal=True),
            ],
        )
    )
    assert "SI: (blank)" in draft.body
    assert "None" not in draft.body


def test_every_field_blank_is_one_sentence_not_seven_questions():
    """An unreadable scan is one problem. Enumerating seven blanks reads as a
    machine working through a template."""
    fields = [
        field(f, None, None)
        for f in (
            "shipper", "consignee", "notify_party", "port_of_loading",
            "port_of_discharge", "container_count", "gross_weight_kg",
        )
    ]
    draft = compose(make(status="NEEDS_REVIEW", review_reason="missing_value", fields=fields))
    assert "none of the details could be read" in draft.body
    assert "(blank)" not in draft.body


# -- a clean check -------------------------------------------------------
def test_a_clean_check_is_confirmed_because_silence_stalls_a_shipment():
    draft = compose(make(status="OK"))
    assert draft.kind == "confirm"
    assert "please proceed to release" in draft.body


def test_a_clean_check_carrying_doubt_is_not_offered_for_approval():
    """Regression. Advisory mode keeps the OK *and* records the concern. A
    confirmation that suppresses it would sound more certain to the customer
    than the run was to itself."""
    assert compose(make(status="OK", concerns=["two readings disagreed on ports"])) is None
