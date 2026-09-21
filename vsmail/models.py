"""Core data types.

`Document` is what every attachment reader returns, whatever the format.
`EmailRecord` mirrors one `inbox/email_*.json` record from the bundle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from vsmail.attachments import attachment_slots


#: Separator the bundle uses ahead of quoted reply history.
_QUOTED_HISTORY = re.compile(r"_{6,}")

#: Security banner some forwarded mail carries; it is not part of the request.
_EXTERNAL_BANNER = re.compile(
    r"WARNING:\s*This email originated outside.*?attachments\.",
    re.IGNORECASE | re.DOTALL,
)

#: Sign-offs that begin the boilerplate signature block.
_SIGN_OFFS = (
    "Best Regards",
    "Best regards",
    "Thanks & Regards",
    "Thanks and Regards",
    "Kind Regards",
    "Warm Regards",
    "Regards,",
)


def trim_body(body: str) -> str:
    """Strip quoted history, the external-mail banner and the signature block.

    Classification hinges on the sender's actual request, which in this bundle
    is a sentence or two buried between a security banner and a long corporate
    signature. Everything removed here is boilerplate that repeats across
    hundreds of emails and would otherwise dominate the prompt.
    """
    body = _EXTERNAL_BANNER.sub("", body)
    body = _QUOTED_HISTORY.split(body)[0]
    for sign_off in _SIGN_OFFS:
        index = body.find(sign_off)
        if index > 0:
            body = body[:index]
            break
    return body.strip()


@dataclass(frozen=True)
class EmailRecord:
    """One email from the bundle's inbox."""

    email_id: str
    sender: str
    subject: str
    body: str
    attachments: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, record: dict) -> EmailRecord:
        return cls(
            email_id=record["email_id"],
            sender=record.get("from", ""),
            subject=record.get("subject", ""),
            body=record.get("body", ""),
            attachments=tuple(record.get("attachments") or ()),
        )

    @property
    def core_body(self) -> str:
        """The sender's request, with boilerplate removed."""
        return trim_body(self.body)

    def attachment_for(self, role: str) -> str | None:
        """The attachment filled into the SI or BL slot, if any.

        Natural customer filenames are accepted as well as the bundle's
        ``_SI`` and ``_BL`` suffixes. A two-file pair with generic names is
        kept in MIME order rather than incorrectly reported as absent.
        """
        return attachment_slots(self.attachments).get(role.upper())


@dataclass(frozen=True)
class Document:
    """An attachment after reading, whatever its original format.

    A document that could not be parsed carries ``readable=False`` and an
    ``error``; one with no text layer carries rasterized ``images`` instead,
    for a vision-capable model to read.
    """

    path: str
    role: str
    text: str = ""
    images: tuple[bytes, ...] = ()
    readable: bool = True
    error: str | None = None
    doc_kind: str | None = None

    @property
    def is_empty(self) -> bool:
        """True when there is nothing for the extractor to work with."""
        return not self.text.strip() and not self.images


@dataclass(frozen=True)
class FieldValues:
    """One field as it appears in each document, before normalization."""

    field: str
    si_value: str | None = None
    bl_value: str | None = None
    si_snippet: str | None = None
    bl_snippet: str | None = None


@dataclass
class Verdict:
    """The pipeline's decision for a single email."""

    email_id: str
    category: str
    status: str = "OK"
    review_reason: str | None = None
    has_defect: bool = False
    defect_fields: list[str] = field(default_factory=list)

    def to_submission_entry(self) -> dict:
        """The exact shape `sample_submission.json` defines."""
        return {
            "category": self.category,
            "status": self.status,
            "review_reason": self.review_reason,
            "has_defect": self.has_defect,
            "defect_fields": list(self.defect_fields),
        }


@dataclass(frozen=True)
class Classification:
    """Which of the five categories an email belongs to."""

    category: str
    confidence: float = 1.0
    rationale: str | None = None


@dataclass(frozen=True)
class Extraction:
    """The seven fields as each document states them.

    Values are raw, exactly as written. Normalization and comparison happen
    afterwards in our own code, never in the model.
    """

    si: dict[str, str | None] = field(default_factory=dict)
    bl: dict[str, str | None] = field(default_factory=dict)
    si_snippets: dict[str, str] = field(default_factory=dict)
    bl_snippets: dict[str, str] = field(default_factory=dict)
    #: Fields two extraction passes read differently. Empty when only one
    #: pass ran, which is the case for any deterministic provider.
    uncertain_fields: tuple[str, ...] = ()

    def missing(self, fields: tuple[str, ...]) -> list[str]:
        """Fields absent from either document."""
        return [f for f in fields if not self.si.get(f) or not self.bl.get(f)]
