"""Client for our own deployed service.

Lets a local run, or the frontend, use the model without ever holding the
API key: the key lives only in the deployed service's environment. The
direct `DeepSeekProvider` stays usable alongside this one, so a deployment
outage never leaves the pipeline with no way to run.
"""
from __future__ import annotations

import base64
import os

import httpx

from vsmail.config import CATEGORIES
from vsmail.models import Classification, Document, EmailRecord, Extraction

_TIMEOUT = httpx.Timeout(180.0, connect=15.0)


class RemoteProvider:
    """Forwards classification and extraction to the deployed service."""

    name = "remote"

    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url or os.environ.get("VS_SERVICE_URL", "")).rstrip("/")
        if not self.url:
            raise RuntimeError("VS_SERVICE_URL is not set")
        self.token = token or os.environ.get("VS_SERVICE_TOKEN", "")
        self._client = httpx.AsyncClient(
            base_url=self.url,
            timeout=_TIMEOUT,
            headers={"X-VS-Token": self.token} if self.token else {},
        )

    async def _post(self, path: str, payload: dict) -> dict:
        response = await self._client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    async def classify(self, email: EmailRecord) -> Classification:
        data = await self._post(
            "/classify",
            {
                "email_id": email.email_id,
                "sender": email.sender,
                "subject": email.subject,
                "body": email.body,
                "attachments": list(email.attachments),
            },
        )
        category = str(data.get("category", "")).upper()
        if category not in CATEGORIES:
            return Classification("GENERAL", confidence=0.0, rationale="unparsed")
        return Classification(
            category=category,
            confidence=float(data.get("confidence", 1.0) or 0.0),
            rationale=data.get("rationale"),
        )

    async def extract(self, si: Document, bl: Document) -> Extraction:
        data = await self._post("/extract", {"si": _wire(si), "bl": _wire(bl)})
        return Extraction(
            si=data.get("si") or {},
            bl=data.get("bl") or {},
            si_snippets=data.get("si_snippets") or {},
            bl_snippets=data.get("bl_snippets") or {},
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _wire(document: Document) -> dict:
    """A document as JSON. Scanned pages travel base64-encoded."""
    return {
        "path": document.path,
        "role": document.role,
        "text": document.text,
        "images": [base64.b64encode(image).decode() for image in document.images],
        "readable": document.readable,
        "doc_kind": document.doc_kind,
    }
