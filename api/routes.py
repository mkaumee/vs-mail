"""Service routes.

The pipeline is the same code the command line runs; nothing here
reimplements classification or comparison.
"""
from __future__ import annotations

import base64
import os

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_token
from api.schemas import CompareIn, EmailIn, ExtractIn, RunIn, SubmitIn
from vsmail import pipeline, submission as submission_module
from vsmail.compare import compare_all, decide
from vsmail.inbox import Bundle
from vsmail.models import Document, EmailRecord
from vsmail.scoring import score

router = APIRouter()
guarded = APIRouter(dependencies=[Depends(require_token)])


def build_provider():
    """The provider this deployment runs, chosen by environment.

    Defaults to the offline mock so the service starts and answers /health
    even before a key is configured.
    """
    name = os.environ.get("VS_PROVIDER", "mock").lower()
    if name == "deepseek":
        from vsmail.llm.deepseek import DeepSeekProvider

        return DeepSeekProvider()
    if name == "remote":
        from vsmail.llm.remote import RemoteProvider

        return RemoteProvider()
    from vsmail.llm.mock import MockProvider

    return MockProvider()


def _record(payload: EmailIn) -> EmailRecord:
    return EmailRecord(
        email_id=payload.email_id,
        sender=payload.sender,
        subject=payload.subject,
        body=payload.body,
        attachments=tuple(payload.attachments),
    )


def _document(payload) -> Document:
    return Document(
        path=payload.path,
        role=payload.role,
        text=payload.text,
        images=tuple(base64.b64decode(image) for image in payload.images),
        readable=payload.readable,
        doc_kind=payload.doc_kind,
    )


@router.get("/health")
async def health() -> dict:
    """Unauthenticated, so a deployment can be checked without the secret."""
    from api.auth import configured_token

    return {
        "status": "ok",
        "provider": os.environ.get("VS_PROVIDER", "mock").lower(),
        "token_configured": bool(configured_token()),
    }


@guarded.post("/classify")
async def classify(payload: EmailIn) -> dict:
    provider = build_provider()
    try:
        result = await provider.classify(_record(payload))
    finally:
        await provider.aclose()
    return {
        "category": result.category,
        "confidence": result.confidence,
        "rationale": result.rationale,
    }


@guarded.post("/extract")
async def extract(payload: ExtractIn) -> dict:
    provider = build_provider()
    try:
        result = await provider.extract(_document(payload.si), _document(payload.bl))
    finally:
        await provider.aclose()
    return {
        "si": result.si,
        "bl": result.bl,
        "si_snippets": result.si_snippets,
        "bl_snippets": result.bl_snippets,
    }


@guarded.post("/compare")
async def compare(payload: CompareIn) -> dict:
    """Extract and decide in one call, with the per-field detail kept."""
    provider = build_provider()
    si, bl = _document(payload.si), _document(payload.bl)
    try:
        extraction = await provider.extract(si, bl)
    finally:
        await provider.aclose()

    email = EmailRecord(payload.email_id, "", "", "", (si.path, bl.path))
    verdict = decide(email, "BL_COMPARISON", si, bl, extraction)
    return {
        "verdict": verdict.to_submission_entry(),
        "fields": [
            {
                "field": c.field,
                "si_value": c.si_value,
                "bl_value": c.bl_value,
                "equal": c.equal,
                "note": c.note,
            }
            for c in compare_all(extraction)
        ],
    }


@guarded.post("/run")
async def run(payload: RunIn) -> dict:
    """Process a whole bundle and return a submission."""
    bundle = Bundle(payload.source) if payload.source else Bundle()
    provider = build_provider()
    try:
        verdicts = await pipeline.run(bundle, provider, concurrency=payload.concurrency)
    finally:
        await provider.aclose()

    result = submission_module.build(verdicts)
    problems = submission_module.validate(result, [e.email_id for e in bundle.emails()])
    return {"submission": result, "problems": problems}


@guarded.post("/submit")
async def submit(payload: SubmitIn) -> dict:
    """Grade a submission against our dev-set labels.

    This is not the organizers' scorer and cannot be. It reports agreement
    with labels we wrote ourselves, which is why the number it returns is
    called devset_score.
    """
    import json
    from pathlib import Path

    devset = Path(__file__).resolve().parent.parent / "tests" / "devset.json"
    if not devset.exists():  # pragma: no cover - defensive
        raise HTTPException(500, detail="dev-set labels are missing")
    labels = json.loads(devset.read_text())["labels"]

    board = score(payload.submission, labels)
    return {
        "devset_score": board.devset_score,
        "note": "scored against our own labels, not ground truth",
        "classification_macro_f1": board.classification_macro_f1,
        "defect_f1": board.defect_f1,
        "end_to_end_f1": board.end_to_end_f1,
        "review_accuracy": board.review_accuracy,
        "labelled": board.labelled,
        "disagreements": board.disagreements,
    }


@guarded.get("/sample_submission")
async def sample_submission() -> dict:
    return Bundle().sample_submission()
