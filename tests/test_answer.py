"""Answering the emails that ask something.

The model writes prose here, which it does not anywhere else in this system.
So most of what is pinned is the fence around it: what it is allowed to see,
what it must cite, and what happens when it has nothing to answer from.
"""
import asyncio

import pytest

from vsmail.answer import ANSWERABLE, compose_answer, question_from
from vsmail.results import Result


class Stub:
    """A provider that answers, recording what it was shown."""

    name = "stub"

    def __init__(self, body="THC is billed separately.", used=None, missing=""):
        self.body, self._used, self.missing = body, used, missing
        self.seen = []

    async def answer(self, question, material):
        self.seen.append((question, material))
        ids = self._used if self._used is not None else [material[0]["id"]]
        return {"body": self.body, "used": ids, "missing": self.missing}

    async def aclose(self):
        pass


class Silent:
    """The deterministic mock: no view on what a charge policy says."""

    name = "silent"


class FakeIndex:
    def __init__(self, hits):
        self._hits = hits

    def search(self, question, **kw):
        return self._hits


class Hit:
    def __init__(self, chunk):
        self.chunk = chunk
        self.score = 1.0


class Chunk:
    def __init__(self, id, fabricated=False):
        self.id, self.fabricated = id, fabricated
        self.heading, self.source, self.text = id, "x.md", "text"

    def as_dict(self):
        return {"id": self.id, "heading": self.heading, "source": self.source,
                "text": self.text, "fabricated": self.fabricated}


def result(category="INVOICE_QUERY", **kw):
    return Result(email_id="email_002", category=category, status="OK",
                  subject="Query on invoice 5250075931", sender="hari@april.com.my", **kw)


class Email:
    body = "Hi, Query on invoice 5250075931: is the THC included?\n\nBest Regards,\nHari"
    subject = "Query on invoice 5250075931"


def run(coro):
    return asyncio.run(coro)


# -- what the model is asked ---------------------------------------------
def test_the_signature_and_banner_are_stripped():
    """54 emails carry the same security banner and nearly all the same
    footer. Left in, every email looks alike to a vector."""
    q = question_from(
        "Subject here",
        "This email originated outside of our organisation. As a security "
        "measure, please exercise caution with E-Mail content and any links "
        "or attachments.\n\nIs the THC included?\n\nBest Regards,\nHari\nDID: +971",
    )
    assert "Is the THC included?" in q
    assert "security measure" not in q
    assert "DID" not in q


def test_quoted_history_is_dropped():
    q = question_from("S", "The actual ask.\n______________\nFrom: someone\nOld thread")
    assert "Old thread" not in q


# -- which lanes get answered --------------------------------------------
@pytest.mark.parametrize("category", ["GENERAL", "SPAM", "BL_COMPARISON"])
def test_only_questions_are_answered(category):
    """GENERAL is deliberately out. Those are berthing reports and RPA
    notices that say 'no action required' — drafting a reply to one is work
    invented rather than saved."""
    draft, why = run(compose_answer(result(category), Email(), FakeIndex([]), Stub()))
    assert draft is None
    assert "only invoice queries" in why
    assert category not in ANSWERABLE


# -- the refusal paths ----------------------------------------------------
def test_a_provider_that_cannot_answer_says_so():
    """The mock must not pretend to have a view on charge policy."""
    draft, why = run(compose_answer(result(), Email(), FakeIndex([]), Silent()))
    assert draft is None
    assert "cannot answer" in why


def test_nothing_retrieved_means_refuse_not_guess():
    stub = Stub()
    draft, why = run(compose_answer(result(), Email(), FakeIndex([]), stub))
    assert draft is None
    assert "nothing in the knowledge base" in why
    assert stub.seen == [], "the model must not be called with no material"


def test_no_index_is_reported_rather_than_ignored():
    draft, why = run(compose_answer(result(), Email(), None, Stub()))
    assert draft is None
    assert "build_index" in why


def test_an_empty_answer_is_not_offered():
    draft, why = run(
        compose_answer(result(), Email(), FakeIndex([Hit(Chunk("charges#1"))]), Stub(body="  "))
    )
    assert draft is None


# -- citations ------------------------------------------------------------
def test_the_model_only_sees_what_was_retrieved():
    stub = Stub()
    index = FakeIndex([Hit(Chunk("charges#1")), Hit(Chunk("invoice:1", True))])
    run(compose_answer(result(), Email(), index, stub))
    _, material = stub.seen[0]
    assert [m["id"] for m in material] == ["charges#1", "invoice:1"]


def test_a_citation_the_model_invented_is_dropped():
    """It can only have used what it was given. Anything else is a
    hallucinated source, and a citation nobody can follow is worse than none."""
    stub = Stub(used=["charges#1", "made_up#9"])
    index = FakeIndex([Hit(Chunk("charges#1"))])
    draft, _ = run(compose_answer(result(), Email(), index, stub))
    assert [c["id"] for c in draft.citations] == ["charges#1"]


def test_fabricated_material_marks_the_draft():
    index = FakeIndex([Hit(Chunk("invoice:5250075931", fabricated=True))])
    draft, _ = run(compose_answer(result(), Email(), index, Stub()))
    assert draft.fabricated is True


def test_policy_only_answers_are_not_marked_fabricated():
    index = FakeIndex([Hit(Chunk("charges#1"))])
    draft, _ = run(compose_answer(result(), Email(), index, Stub()))
    assert draft.fabricated is False


# -- what it could not answer --------------------------------------------
def test_a_gap_is_stated_in_the_body_rather_than_filled():
    stub = Stub(missing="The charge lines for this invoice are not in front of me.")
    index = FakeIndex([Hit(Chunk("charges#1"))])
    draft, _ = run(compose_answer(result(), Email(), index, stub))
    assert "not in front of me" in draft.body
    assert draft.missing == stub.missing


# -- the shape of the reply ----------------------------------------------
def test_it_is_greeted_and_signed_and_stays_in_thread():
    index = FakeIndex([Hit(Chunk("charges#1"))])
    draft, _ = run(compose_answer(result(), Email(), index, Stub()))
    assert draft.body.startswith("Dear Hari,")
    assert draft.body.rstrip().endswith("Thanks,")
    assert draft.subject.startswith("RE: ")
    assert draft.kind == "answer"
