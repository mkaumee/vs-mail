"""Writing the triage back onto the real messages.

The point of doing this at all: the decision shows up in Gmail itself, in the
mailbox the ops desk already lives in, rather than only in a file we produced.
"""
from __future__ import annotations

from vsmail.config import CATEGORIES

#: Applied to everything this system seeds, so a reset knows what to remove.
#: Gmail cannot search on an arbitrary header, but it can search on a label.
SEED_LABEL = "VS/Seed"

#: One per category, plus a flag for anything a person should look at.
CATEGORY_LABELS = {
    "BL_COMPARISON": "VS/BL-Comparison",
    "SI_REQUEST": "VS/SI-Request",
    "INVOICE_QUERY": "VS/Invoice",
    "GENERAL": "VS/General",
    "SPAM": "VS/Spam",
}
REVIEW_LABEL = "VS/Needs-Review"
DEFECT_LABEL = "VS/Defect-Found"

assert set(CATEGORY_LABELS) == set(CATEGORIES), "a category has no label"


class Labels:
    """Label ids by name, created on demand and remembered."""

    def __init__(self, service):
        self.service = service
        self._ids: dict[str, str] = {}

    def _load(self) -> None:
        existing = self.service.users().labels().list(userId="me").execute()
        self._ids = {label["name"]: label["id"] for label in existing.get("labels", [])}

    def id_for(self, name: str) -> str:
        if not self._ids:
            self._load()
        if name not in self._ids:
            created = (
                self.service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            self._ids[name] = created["id"]
        return self._ids[name]

    def apply(self, message_id: str, names: list[str]) -> None:
        if not names:
            return
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [self.id_for(name) for name in names]},
        ).execute()


def labels_for(entry: dict) -> list[str]:
    """Which labels a verdict earns.

    A mismatch gets its own label as well as its category: on a busy morning
    the thing worth seeing first is which drafts have errors in them.
    """
    names = [CATEGORY_LABELS.get(entry["category"], "VS/General")]
    if entry.get("status") == "NEEDS_REVIEW":
        names.append(REVIEW_LABEL)
    elif entry.get("status") == "MISMATCH":
        names.append(DEFECT_LABEL)
    return names
