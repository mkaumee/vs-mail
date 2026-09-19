"""DeepSeek client.

Runs inside the deployed service, which is the only place the API key
exists. The key is never read from, or written to, this repository.

The model is natively multimodal, so the six image-only PDF pages in the
bundle go to it as PNGs rather than through a separate OCR stage.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

import httpx

from vsmail.config import CATEGORIES, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, FIELDS
from vsmail.models import Classification, Document, EmailRecord, Extraction
from vsmail.normalize import is_placeholder
from vsmail.consensus import merge
from vsmail.prompts import CLASSIFY_SYSTEM, EXTRACT_SYSTEM

#: Retried on transient failures; a 520-email run should not die on one 503.
_RETRIES = 3
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


class DeepSeekProvider:
    """Calls the DeepSeek chat-completions API directly."""

    name = "deepseek"

    def __init__(self, api_key: str | None = None, model: str = DEEPSEEK_MODEL):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. It belongs in the deployed "
                "service's environment, not in this repository."
            )
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            timeout=_TIMEOUT,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

    async def _json_call(self, system: str, content: Any) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        last: Exception | None = None
        for attempt in range(_RETRIES):
            try:
                response = await self._client.post("/chat/completions", json=payload)
                response.raise_for_status()
                body = response.json()
                return json.loads(body["choices"][0]["message"]["content"])
            except Exception as exc:  # network, 5xx, or malformed JSON
                last = exc
                if attempt == _RETRIES - 1:
                    raise
        raise RuntimeError(str(last))  # pragma: no cover - unreachable

    async def classify(self, email: EmailRecord) -> Classification:
        manifest = ", ".join(email.attachments) or "(none)"
        user = (
            f"From: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Attachments: {manifest}\n\n"
            f"Body:\n{email.core_body}"
        )
        data = await self._json_call(CLASSIFY_SYSTEM, user)
        category = str(data.get("category", "")).strip().upper()
        if category not in CATEGORIES:
            # An unusable answer must not silently become a confident guess.
            return Classification("GENERAL", confidence=0.0, rationale=f"unparsed: {category!r}")
        return Classification(
            category=category,
            confidence=float(data.get("confidence", 1.0) or 0.0),
            rationale=str(data.get("rationale") or "")[:200] or None,
        )

    async def extract(
        self, si: Document, bl: Document, reversed_order: bool = False
    ) -> Extraction:
        parts: list[dict] = [{"type": "text", "text": _describe(si, bl, reversed_order)}]
        # Images follow in the order the text announced them.
        for document in ((bl, si) if reversed_order else (si, bl)):
            for image in document.images:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(image).decode()
                        },
                    }
                )
        # A text-only pair needs no multimodal envelope.
        content: Any = parts if len(parts) > 1 else parts[0]["text"]
        data = await self._json_call(EXTRACT_SYSTEM, content)
        return Extraction(
            si=_fields(data.get("si")),
            bl=_fields(data.get("bl")),
            si_snippets=_snippets(data.get("si_snippets")),
            bl_snippets=_snippets(data.get("bl_snippets")),
        )

    async def extract_twice(self, si: Document, bl: Document) -> Extraction:
        """Read both documents twice and record where the readings differ.

        The second pass presents the documents in the opposite order rather
        than repeating the same request. At temperature 0 a repeat returns
        identical JSON, so it would agree with itself and catch nothing; a
        value that changes when the documents are swapped is genuinely
        unstable.
        """
        first, second = await asyncio.gather(
            self.extract(si, bl),
            self.extract(si, bl, reversed_order=True),
        )
        return merge(first, second)

    async def aclose(self) -> None:
        await self._client.aclose()


def _describe(si: Document, bl: Document, reversed_order: bool = False) -> str:
    """Both documents in one message, so the model sees them side by side.

    `reversed_order` puts the draft bill of lading first. The labels still say
    which is which, so a correct reading is unchanged by the swap — that is
    the point of asking twice.
    """
    def body(document: Document, label: str) -> str:
        if document.text.strip():
            return f"=== {label} ({document.path}) ===\n{document.text}"
        return (
            f"=== {label} ({document.path}) ===\n"
            f"(no text layer; {len(document.images)} scanned page(s) follow as images, "
            f"in order: {label} first)"
        )

    si_text = body(si, "SHIPPING INSTRUCTION")
    bl_text = body(bl, "DRAFT BILL OF LADING")
    if reversed_order:
        return f"{bl_text}\n\n{si_text}"
    return f"{si_text}\n\n{bl_text}"


def _fields(raw: Any) -> dict[str, str | None]:
    values = raw if isinstance(raw, dict) else {}
    result: dict[str, str | None] = {}
    for field in FIELDS:
        value = values.get(field)
        if value is None:
            result[field] = None
            continue
        text = str(value).strip()
        # A model sometimes echoes the document's placeholder, or writes
        # "null" as text, rather than returning a JSON null.
        result[field] = None if text.lower() == "null" or is_placeholder(text) else text
    return result


def _snippets(raw: Any) -> dict[str, str]:
    values = raw if isinstance(raw, dict) else {}
    return {
        field: str(values[field])[:300]
        for field in FIELDS
        if values.get(field) not in (None, "")
    }
