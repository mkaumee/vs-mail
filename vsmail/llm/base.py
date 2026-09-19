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


# Two capabilities are deliberately *not* on this protocol, and are looked up
# with `getattr` instead:
#
#   extract_twice(si, bl)      -> vsmail.consensus
#   judge_equivalence(pairs)   -> vsmail.equivalence
#
# Both are meaningful only for a model. A deterministic provider repeating
# itself learns nothing, and has no opinion about whether two company names
# denote the same company. Requiring them here would force the mock to
# implement stubs that lie about having an opinion; leaving them optional lets
# absence mean what it actually means.
