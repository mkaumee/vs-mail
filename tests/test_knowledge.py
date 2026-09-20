"""The knowledge base, and what it retrieves.

Retrieval is the part that decides whether the answering side is useful or
confidently wrong, so it is measured against the five question shapes the
inbox actually contains rather than spot-checked.
"""
import pytest

from vsmail.knowledge import embed
from vsmail.knowledge.chunks import load_all, split_markdown, KNOWLEDGE
from vsmail.knowledge.index import Index, MIN_SCORE, available

pytestmark = pytest.mark.skipif(
    not (available() and embed.available()),
    reason="needs the committed model and a built index",
)


@pytest.fixture(scope="module")
def index() -> Index:
    return Index()


# -- the corpus ----------------------------------------------------------
def test_the_readme_is_not_part_of_the_corpus():
    """It describes the corpus. Retrieving it would answer a customer's
    question with our own file listing."""
    assert all(c.source != "README.md" for c in load_all())


def test_records_are_marked_fabricated():
    chunks = load_all()
    records = [c for c in chunks if c.source == "records.json"]
    assert records
    assert all(c.fabricated for c in records)
    assert all(not c.fabricated for c in chunks if c.source.endswith(".md"))


def test_a_chunk_carries_its_heading_into_the_embedded_text():
    """"Free time" alone carries the topic the body below assumes."""
    chunks = split_markdown(KNOWLEDGE / "detention.md")
    free = next(c for c in chunks if c.heading == "Free time")
    assert free.text.startswith("Detention and demurrage — Free time")


# -- retrieval, by question type -----------------------------------------
QUESTIONS = [
    ("Query on invoice 5250075931: is the THC / local charge included or "
     "billed separately? Please advise the breakdown.", "charges.md"),
    ("Please find the D&D / detention charges for 5AAT-94519. Kindly confirm "
     "the amount before we release payment.", "detention.md"),
    ("We note the GR is still missing for invoice 5250070084. Kindly arrange "
     "to post the GR so we can proceed with billing.", "billing.md"),
    ("Requesting to cancel invoice 5250075652 and reverse the PGI. Reason: "
     "booking amended.", "billing.md"),
    ("Please assist to send the draft BL for 5RCY-68239 for checking asap.",
     "documents.md"),
]


@pytest.mark.parametrize("question,expected", QUESTIONS)
def test_the_right_document_is_retrieved(index, question, expected):
    policy = [h for h in index.search(question) if not h.chunk.fabricated]
    assert policy, "nothing retrieved"
    assert policy[0].chunk.source == expected


def test_a_question_the_corpus_does_not_cover_retrieves_nothing(index):
    """An empty result is the honest answer, and the caller turns it into a
    refusal. Retrieving something irrelevant would give the model material to
    be confidently wrong from."""
    assert index.search("What is the office holiday schedule for next year?") == []


# -- identifiers are looked up, never matched ----------------------------
def test_a_named_record_is_looked_up_exactly(index):
    """Regression. Every booking reference embeds almost identically, so
    asking about 5AAT-94519 retrieved 5SUS-22342 at 0.74 — a confidently
    wrong record, which is the worst thing to hand a model."""
    hits = index.search("D&D charges for 5AAT-94519, confirm the amount")
    records = [h for h in hits if h.chunk.fabricated]
    assert [h.chunk.id for h in records] == ["booking:5AAT-94519"]
    assert records[0].score == 1.0


def test_records_are_never_reached_by_similarity(index):
    """A question naming no reference gets policy only."""
    hits = index.search("is the terminal handling charge included in freight?")
    assert all(not h.chunk.fabricated for h in hits)


def test_both_an_invoice_and_a_booking_can_be_named(index):
    hits = index.records_named_in("invoice 5250075931 on booking 5AKR-61849")
    assert {h.chunk.id for h in hits} == {"invoice:5250075931", "booking:5AKR-61849"}


def test_an_unknown_reference_is_simply_absent(index):
    assert index.records_named_in("invoice 5299999999") == []


# -- the encoder ---------------------------------------------------------
def test_vectors_are_normalised_so_a_dot_product_is_cosine():
    import numpy as np

    v = embed.encode(["Terminal handling charges are billed separately."])
    assert v.shape == (1, embed.DIMENSIONS)
    assert np.isclose(np.linalg.norm(v[0]), 1.0, atol=1e-5)


def test_the_query_prefix_is_applied_to_questions_only():
    """bge is trained asymmetrically. Skipping the prefix runs fine and
    retrieves worse, which is the kind of bug that hides."""
    import numpy as np

    bare = embed.encode(["is THC included?"])[0]
    prefixed = embed.encode_query("is THC included?")
    assert not np.allclose(bare, prefixed)


def test_the_threshold_sits_between_real_and_irrelevant(index):
    real = index.search(QUESTIONS[0][0])
    assert max(h.score for h in real if not h.chunk.fabricated) > MIN_SCORE + 0.1
