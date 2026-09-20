"""Answering the emails that ask something, rather than send a document.

Comparison requests get a composed reply (`vsmail.reply`) because their
sentences never vary. These do not: "is the THC included?" and "cancel the
invoice and reverse the PGI" need different prose drawn from different
material, so the model writes the body.

What it is allowed to write from is tightly bounded. It sees only the chunks
retrieved for this email, it is told to cite each one it uses, and it is told
to name what it cannot answer rather than fill the gap. All three come back
and all three reach the screen, because a drafted answer nobody can check
against a source is not usable in a domain where the reply quotes money.

The model never sends, and never decides whether to send.
"""
from __future__ import annotations

import re

from vsmail.reply import Draft, _greeting, _subject

#: Which lanes are worth answering.
#:
#: GENERAL is deliberately absent. Reading them showed what they are —
#: berthing reports, outstanding-item lists, RPA notices that say "no action
#: required", holiday greetings. Drafting a reply to an automated notification
#: is work invented rather than saved.
ANSWERABLE = ("INVOICE_QUERY", "SI_REQUEST")

_SIGNATURE = re.compile(
    r"(best regards|kind regards|thanks & regards|regards,|warm regards)", re.I
)
_QUOTED = re.compile(r"_{6,}")
_BANNER = re.compile(
    r"^.{0,80}?this email originated outside of our organisation.*?attachments\.?\s*",
    re.I | re.S,
)


def question_from(subject: str, body: str) -> str:
    """The part of the email that is actually asking something.

    Strips the security banner, the quoted history and the signature block.
    Left in, they dominate the embedding — 54 of these emails carry the same
    security banner and nearly all carry the same footer, so uncleaned they
    all look alike to a vector.
    """
    body = _QUOTED.split(body or "")[0]
    body = _BANNER.sub("", body)
    match = _SIGNATURE.search(body)
    if match:
        body = body[: match.start()]
    return f"{(subject or '').strip()}\n\n{' '.join(body.split())}".strip()


async def compose_answer(result, email, index, provider) -> tuple[Draft | None, str]:
    """Draft a reply for one email. Returns the draft and, if none, why.

    The reason matters as much as the draft: "the model cannot answer" and
    "the corpus does not cover this" want different responses from a person,
    and both are better than a confident guess.
    """
    if result.category not in ANSWERABLE:
        return None, "only invoice queries and document requests are answered"

    answer = getattr(provider, "answer", None)
    if answer is None:
        # The deterministic mock has no view on what a charge policy says and
        # must not pretend to. Offline runs stay honest and the suite stays
        # free of network calls.
        return None, "this provider cannot answer; run with --provider deepseek"

    if index is None:
        return None, "no knowledge index; run scripts/build_index.py"

    question = question_from(result.subject, getattr(email, "body", ""))
    hits = index.search(question)
    if not hits:
        # Nothing in the corpus is about this. Refusing is the answer.
        return None, "nothing in the knowledge base covers this email"

    material = [h.chunk.as_dict() for h in hits]
    written = await answer(question, material)
    body = written.get("body", "").strip()
    if not body:
        return None, "the model returned nothing"

    # Only credit citations that name material actually put in front of it.
    offered = {c["id"]: c for c in material}
    used = [offered[i] for i in written.get("used", []) if i in offered]
    cited = used or list(offered.values())

    missing = written.get("missing", "").strip()
    full = f"{_greeting(result.sender)}\n\n{body}"
    if missing:
        full += f"\n\n{missing}"
    full += "\n\nThanks,"

    return (
        Draft(
            to=result.sender,
            subject=_subject(result.subject),
            body=full,
            kind="answer",
            citations=tuple(
                {"id": c["id"], "heading": c["heading"], "source": c["source"],
                 "fabricated": c["fabricated"]}
                for c in cited
            ),
            fabricated=any(c["fabricated"] for c in cited),
            missing=missing,
        ),
        "",
    )
