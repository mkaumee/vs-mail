"""The provider interface.

Three implementations sit behind it: a deterministic mock that needs no
network, the DeepSeek client that runs inside the deployed service, and a
remote client that calls that service. Keeping the direct and remote paths
both usable means a deployment outage cannot leave the pipeline with no way
to run.

The interface is task-shaped rather than prompt-shaped — `classify` and
`extract`, not `complete` — so the mock can answer with rules instead of
having to interpret a prompt.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from vsmail.models import Classification, Document, EmailRecord, Extraction


@runtime_checkable
class Provider(Protocol):
    """Whatever decides an email's category and reads fields from documents."""

    name: str

    async def classify(self, email: EmailRecord) -> Classification:
        """Sort one email into a category."""
        ...

    async def extract(self, si: Document, bl: Document) -> Extraction:
        """Read the seven fields from each document, raw and uncompared."""
        ...

    async def aclose(self) -> None:
        """Release any network resources."""
        ...
