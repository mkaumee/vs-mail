"""Writing the reply a checker would otherwise type.

What actually happens when this system finds something is an email. The
document being checked is a *draft* — "kindly verify the BL matches the SI
before we release to the line" (email_107), "revert with any discrepancy
asap" (email_119). Nobody here redrafts a bill of lading. They reply saying
what is wrong, and the carrier corrects its draft.

That reply is formulaic, and every value it needs is already on screen by the
time a person reads it. Making them retype it is the waste.

**Composed in code, not by the model, and the reason is the same one that
keeps the comparator deterministic.** The strings in a correction email are
the exact values from the documents — a consignee name, a weight — and they
carry legal weight. A model asked to write this email would be retyping them,
which is a transcription risk with no upside: the sentences around them are
the same every time. So the model reads documents and the template writes
prose, and neither does the other's job.

Nothing here sends anything. It produces text for a person to approve, which
is the whole point.
"""
from __future__ import annotations

from dataclasses import dataclass

from vsmail.config import FIELDS

#: How each field reads in a sentence a shipping clerk would write.
LABELS: dict[str, str] = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify party",
    "port_of_loading": "Port of loading",
    "port_of_discharge": "Port of discharge",
    "container_count": "Container count",
    "gross_weight_kg": "Gross weight",
}

#: What to ask for when the comparison could not run at all. Each says what is
#: missing and what would unblock it, because "we cannot check this" on its own
#: puts the work back on the sender without telling them what to do.
BLOCKED: dict[str, tuple[str, str]] = {
    "missing_attachment": (
        "one of the two documents did not arrive",
        "Could you resend with both the shipping instruction and the draft "
        "bill of lading attached?",
    ),
    "unreadable": (
        "one of the attachments will not open",
        "Could you resend it, ideally as a PDF saved rather than scanned?",
    ),
    "wrong_doc_type": (
        "one of the attachments is not the document it should be",
        "Could you resend with the shipping instruction and the draft bill of "
        "lading themselves?",
    ),
    "missing_value": (
        "some fields are blank on one side, so they cannot be compared",
        "Could you confirm the values below?",
    ),
}

#: Mailbox names that belong to a desk rather than a person. Addressing
#: "Dear Docs," to docs@ is worse than not trying: it reads as a mail merge
#: that guessed, which is the impression this whole feature is trying to
#: avoid giving.
ROLE_ADDRESSES = frozenset(
    {
        "docs", "doc", "documentation", "exports", "export", "imports",
        "import", "sales", "info", "admin", "support", "logistics",
        "shipping", "accounts", "accounting", "billing", "enquiries",
        "inquiries", "customerservice", "customer", "service", "cs", "ops",
        "operations", "team", "office", "contact", "hello", "mail",
    }
)

SIGN_OFF = "Thanks,"


@dataclass(frozen=True)
class Draft:
    """A reply waiting for a person to approve it."""

    to: str
    subject: str
    body: str
    #: What this reply is for, so the page can label it honestly.
    kind: str
    #: Where an answered reply drew its material from. Empty for the composed
    #: ones, which quote the documents in front of the reader. A drafted
    #: answer nobody can check against a source is not usable here.
    citations: tuple = ()
    #: True when any cited material was invented for the demo. Carried to the
    #: screen — quoting a fabricated charge to a customer unmarked would be
    #: worse than declining to answer.
    fabricated: bool = False
    #: What the material did not cover, said plainly rather than filled in.
    missing: str = ""

    def as_dict(self) -> dict:
        return {
            "to": self.to,
            "subject": self.subject,
            "body": self.body,
            "kind": self.kind,
            "citations": [dict(c) for c in self.citations],
            "fabricated": self.fabricated,
            "missing": self.missing,
        }


def _subject(original: str) -> str:
    """Reply in the same thread rather than starting a new one.

    A correction that arrives as a fresh subject line has to be matched back
    to the shipment by hand, which is exactly the work being saved.
    """
    subject = (original or "").strip() or "(no subject)"
    return subject if subject.upper().startswith("RE:") else f"RE: {subject}"


def _greeting(sender: str) -> str:
    """"Dear Deswita," where the address gives us a first name to use.

    The bundle's own correspondents write this way. Where the address does not
    yield a name, "Dear Team" is what they fall back to, so we do too.
    """
    local = (sender or "").split("@")[0].lower()
    if local in ROLE_ADDRESSES:
        return "Dear Team,"
    parts = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    first = parts[0] if parts else ""
    if first.isalpha() and len(first) > 1 and first not in ROLE_ADDRESSES:
        return f"Dear {first.capitalize()},"
    return "Dear Team,"


def _lines(fields: list[dict], wanted: set[str]) -> list[str]:
    """One line per field, quoting both documents exactly as written."""
    order = {name: i for i, name in enumerate(FIELDS)}
    rows = [f for f in fields if f.get("field") in wanted]
    rows.sort(key=lambda f: order.get(f.get("field"), 99))

    out = []
    for row in rows:
        label = LABELS.get(row.get("field"), row.get("field", ""))
        si = row.get("si")
        bl = row.get("bl")
        si_text = f'"{si}"' if si else "(blank)"
        bl_text = f'"{bl}"' if bl else "(blank)"
        out.append(f"  {label}\n    SI: {si_text}\n    Draft BL: {bl_text}")
    return out


def compose(result) -> Draft | None:
    """The reply for one checked email, or None if none is warranted.

    `result` is a `vsmail.results.Result` or anything with the same fields.
    """
    if result.category != "BL_COMPARISON":
        # Only a comparison request is owed one of these. Triaging an invoice
        # query into a lane is not grounds for writing to anybody.
        return None

    greeting = _greeting(result.sender)
    subject = _subject(result.subject)
    fields = list(result.fields or [])

    if result.status == "MISMATCH":
        named = set(result.defect_fields or [])
        lines = _lines(fields, named)
        if not lines:
            # Announcing discrepancies and then listing none is worse than
            # saying less. Per-field detail is normally present, but a result
            # written by an older run or loaded without it gets here, and that
            # email must never reach a customer.
            listed = ", ".join(LABELS.get(f, f).lower() for f in FIELDS if f in named)
            lines = [f"  {listed or 'one or more fields'}"]
        body = "\n".join(
            [
                greeting,
                "",
                "Thank you for the draft bill of lading. Checking it against "
                "the shipping instruction, the following do not agree:",
                "",
                *lines,
                "",
                "Kindly amend the draft and resend for confirmation. The "
                "remaining fields match.",
                "",
                SIGN_OFF,
            ]
        )
        return Draft(result.sender, subject, body, "mismatch")

    if result.status == "NEEDS_REVIEW":
        why, ask = BLOCKED.get(
            result.review_reason or "",
            ("the comparison could not be completed", "Could you take a look?"),
        )
        blank = {
            f["field"]
            for f in fields
            if f.get("si") in (None, "") or f.get("bl") in (None, "")
        }
        # Every field blank is not seven separate questions — it is one
        # document that could not be read. Listing all seven reads as a
        # machine enumerating a template, and asks the sender to answer
        # something nobody would phrase that way.
        if fields and len(blank) == len(FIELDS):
            why = "none of the details could be read from the documents"
            ask = (
                "Could you resend them as text rather than a scan, or confirm "
                "the details in a reply?"
            )
            blank = set()

        body = "\n".join(
            [
                greeting,
                "",
                f"Thank you for the draft bill of lading. We cannot confirm it "
                f"yet — {why}.",
                "",
                ask,
                *(["", *_lines(fields, blank)] if blank else []),
                "",
                SIGN_OFF,
            ]
        )
        return Draft(result.sender, subject, body, result.review_reason or "blocked")

    # Everything matched. This reply matters as much as the others: the draft
    # is held until someone confirms it, so silence is what stalls a shipment.
    #
    # Unless the run recorded doubt. Advisory mode keeps the OK *and* the
    # concern — two readings that disagreed, or an equivalence the model
    # disputed — and a confirmation that suppresses it would be the system
    # sounding more certain to the customer than it was to itself. It is not
    # offered for approval; a person looks first.
    if result.concerns:
        return None

    body = "\n".join(
        [
            greeting,
            "",
            "Thank you for the draft bill of lading. We have checked it "
            "against the shipping instruction and all details agree — shipper, "
            "consignee, notify party, ports, container count and gross weight.",
            "",
            "Confirmed from our side; please proceed to release.",
            "",
            SIGN_OFF,
        ]
    )
    return Draft(result.sender, subject, body, "confirm")
