"""Service routes.

The pipeline is the same code the command line runs; nothing here
reimplements classification or comparison.
"""
from __future__ import annotations

import base64
import os

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_token
from api.schemas import CompareIn, EmailIn, ExtractIn, ResolveIn, RunIn, SubmitIn
from vsmail import pipeline, submission as submission_module
from vsmail.compare import compare_all, decide
from vsmail.inbox import Bundle
from vsmail.models import Document, EmailRecord
from vsmail.review import ReviewStore
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


def _store() -> ReviewStore:
    return ReviewStore(os.environ.get("VS_REVIEW_STORE", "review.json"))


@guarded.get("/review")
async def review_queue() -> dict:
    """Cases waiting on a person, worst first.

    Ordered by what a wrong value actually costs — consignee and notify party
    carry legal title, gross weight is a SOLAS declaration — rather than by
    arrival.
    """
    queue = _store().queue()
    return {
        "open": len(queue),
        "cases": [
            {
                "email_id": case.email_id,
                "reason": case.reason,
                "severity": case.severity,
                "fields_at_issue": case.evidence.get("fields_at_issue") or [],
                "concerns": case.evidence.get("concerns") or [],
            }
            for case in queue
        ],
    }


@guarded.get("/review/{email_id}")
async def review_case(email_id: str) -> dict:
    case = _store().get(email_id)
    if case is None:
        raise HTTPException(404, detail=f"no case for {email_id}")
    return {
        "email_id": case.email_id,
        "reason": case.reason,
        "state": case.state,
        "severity": case.severity,
        "opened_at": case.opened_at,
        "evidence": case.evidence,
        "corrections": case.corrections,
        "settled": case.settled,
        "audit": case.audit,
    }


@guarded.post("/review/{email_id}/resolve")
async def review_resolve(email_id: str, payload: ResolveIn) -> dict:
    """Record a decision.

    Supplied values are compared like any other reading on the next run; the
    verdict is never written directly. `settle` is the exception and is
    recorded as such.
    """
    store = _store()
    try:
        case = store.resolve(
            email_id,
            by=payload.by,
            confirm=payload.confirm,
            si=payload.si,
            bl=payload.bl,
            settle=payload.settle,
            note=payload.note,
        )
    except KeyError:
        raise HTTPException(404, detail=f"no case for {email_id}")
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))
    return {"email_id": case.email_id, "state": case.state, "audit": case.audit}


@guarded.post("/review/{email_id}/retry")
async def review_retry(email_id: str) -> dict:
    """Reprocess one email, without redoing the other 519.

    A processing failure should be recoverable on its own.
    """
    bundle = Bundle()
    store = _store()
    try:
        email = bundle.get(email_id)
    except Exception:
        raise HTTPException(404, detail=f"no such email: {email_id}")

    provider = build_provider()
    try:
        processed = await pipeline.process_email(bundle, provider, email, store=store)
    finally:
        await provider.aclose()

    store.sync([processed])
    return {
        "email_id": email_id,
        "verdict": processed.verdict.to_submission_entry(),
        "concerns": list(processed.concerns),
    }
