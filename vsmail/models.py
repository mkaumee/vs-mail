"""Core data types.

`Document` is what every attachment reader returns, whatever the format.
`EmailRecord` mirrors one `inbox/email_*.json` record from the bundle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


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

        Role comes from the filename, never from the document's own heading:
        two SI files in this bundle are titled "BILL OF LADING INSTRUCTION".
        """
        marker = f"_{role.upper()}."
        for path in self.attachments:
            if marker in path.upper():
                return path
        return None


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
