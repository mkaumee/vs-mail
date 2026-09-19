"""Request and response bodies for the service."""
from __future__ import annotations

from pydantic import BaseModel, Field


class EmailIn(BaseModel):
    email_id: str = "email_x"
    sender: str = ""
    subject: str = ""
    body: str = ""
    attachments: list[str] = Field(default_factory=list)


class DocumentIn(BaseModel):
    path: str
    role: str
    text: str = ""
    #: Scanned pages, base64-encoded PNG.
    images: list[str] = Field(default_factory=list)
    readable: bool = True
    doc_kind: str | None = None


class ExtractIn(BaseModel):
    si: DocumentIn
    bl: DocumentIn


class CompareIn(ExtractIn):
    email_id: str = "email_x"


class RunIn(BaseModel):
    source: str | None = None
    concurrency: int = 12


class SubmitIn(BaseModel):
    submission: dict


class ResolveIn(BaseModel):
    """What a reviewer decided about a case."""

    by: str = "reviewer"
    confirm: bool = False
    #: Values supplied or corrected, by field. These are compared normally.
    si: dict[str, str] = Field(default_factory=dict)
    bl: dict[str, str] = Field(default_factory=dict)
    #: An outcome forced without values. Bypasses the comparator, so it is
    #: recorded distinctly from a correction.
    settle: dict | None = None
    note: str = ""
