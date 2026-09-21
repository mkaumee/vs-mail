"""Everything the browser talks to.

The existing routes serve the pipeline. These serve the app: an inbox to
look at, buttons that start work, and progress to watch while it runs.
"""
from __future__ import annotations

import asyncio
import mimetypes
import os
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response

from api.auth import require_token
from api.routes import build_provider
from vsmail import pipeline, submission as submission_module
from vsmail.attachments import attachment_name, attachment_slots
from vsmail.documents import read_document
from vsmail.inbox import Bundle
from vsmail.jobs import JOBS, RUNNING
from vsmail.results import ResultStore
from vsmail.review import OPEN, ReviewStore

app_router = APIRouter(dependencies=[Depends(require_token)])

#: The OAuth callback cannot be guarded: Google redirects the operator's
#: browser to it, and a browser redirect carries no header. See the callback
#: itself for what stands in for the token there.
oauth_router = APIRouter()


def _results() -> ResultStore:
    return ResultStore(os.environ.get("VS_RESULTS_STORE", "results.json"))


def _review() -> ReviewStore:
    return ReviewStore(os.environ.get("VS_REVIEW_STORE", "review.json"))


def _result_source() -> str:
    """Read an existing result from the source that produced it."""
    return (os.environ.get("VS_RESULT_SOURCE") or _results().source or "gmail").strip()


def _source(name: str):
    """A bundle folder or a real mailbox, behind the same three methods."""
    if name == "gmail":
        from vsmail.gmail.client import service
        from vsmail.gmail.source import GmailSource

        return GmailSource(service())
    return Bundle() if name in ("", "bundle") else Bundle(name)


def _email_from_source(email_id: str):
    """Load one email, using its stored Gmail id when available.

    New results open with one Gmail lookup. The fallback keeps results written
    before Gmail ids were stored readable until their next run.
    """
    source_name = _result_source()
    source = _source(source_name)
    result = _results().results.get(email_id)
    if source_name == "gmail" and result and result.gmail_message_id:
        return source, source.get_message(result.gmail_message_id)
    email = source.get(email_id)
    if source_name == "gmail" and result:
        # Upgrade results written before Gmail ids were persisted. This first
        # lookup may scan once; every later card load is direct.
        message_id = source.message_id_for(email_id)
        if message_id:
            store = _results()
            current = store.results.get(email_id)
            if current:
                current.gmail_message_id = message_id
                store.save()
    return source, email


# -- looking at the inbox ------------------------------------------------
@app_router.get("/inbox")
async def inbox() -> dict:
    """The mailbox as lanes, comparison requests first.

    Sorting one long list by arrival buries the work. The lane that matters
    is the one holding documents to check.
    """
    store = _results()
    review_cases = _review().queue()
    lanes = store.lanes()
    # HELP is a work queue, not a submission category. Keeping the original
    # category intact is essential because the judging schema permits exactly
    # five categories, while the screen still needs one place for every open
    # human-review case.
    lanes["HELP"] = [
        store.results[case.email_id]
        for case in review_cases
        if case.email_id in store.results
    ]
    stats = store.stats()
    stats["awaiting_review"] = len(review_cases)
    return {
        "stats": stats,
        "lanes": {
            name: [asdict(r) for r in items]
            for name, items in lanes.items()
        },
    }


@app_router.get("/inbox/{email_id}")
async def inbox_item(email_id: str) -> dict:
    result = _results().results.get(email_id)
    if result is None:
        raise HTTPException(404, detail=f"nothing recorded for {email_id}")
    case = _review().get(email_id)
    return {
        "result": asdict(result),
        "case": {
            "state": case.state,
            "reason": case.reason,
            "corrections": case.corrections,
            "audit": case.audit,
        }
        if case
        else None,
    }


@app_router.post("/inbox/{email_id}/recheck")
async def recheck(email_id: str) -> dict:
    """Reprocess one email and update what the page reads.

    This is what makes a resolution visible. `/review/{id}/resolve` records a
    reviewer's value but deliberately does not write a verdict — the
    comparator has to run again over it. Until something does that, the page
    keeps showing the result the original run stored, so supplying a value
    looks like it did nothing.

    Only this email is reprocessed; the other 519 are left alone.
    """
    try:
        bundle, email = await asyncio.to_thread(_email_from_source, email_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, detail=f"no such email: {email_id}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, detail=f"The mailbox could not load this email: {exc}")

    review = _review()
    provider = build_provider()
    try:
        processed = await pipeline.process_email(bundle, provider, email, store=review)
    finally:
        await provider.aclose()

    # The case is re-synced too, so a resolution that did not go far enough
    # reopens rather than vanishing from the queue.
    review.sync([processed])
    result = _results().update_one(processed, email)
    return {"result": asdict(result)}


@app_router.get("/inbox/{email_id}/reply")
async def reply_draft(email_id: str) -> dict:
    """The reply a checker would otherwise type, for them to approve.

    Composed rather than generated: the values in a correction email are the
    exact strings from the documents and carry legal weight, so nothing
    paraphrases them.
    """
    from vsmail.reply import compose, manual

    result = _results().results.get(email_id)
    if result is None:
        raise HTTPException(404, detail=f"nothing recorded for {email_id}")

    # Help is intentionally manual: the evidence remains on screen, while the
    # reply starts empty so the reviewer writes the decision they reached.
    case = _review().get(email_id)
    draft = manual(result) if case and case.state == OPEN else compose(result)
    if draft is not None:
        return {"draft": draft.as_dict()}

    # Everything else that asks something is answered from the knowledge base.
    # Slower — it retrieves and then calls the model — which is what the
    # page's one-ahead prefetch exists to hide.
    from vsmail.answer import ANSWERABLE, compose_answer
    from vsmail.knowledge.index import get_index

    if result.category not in ANSWERABLE:
        # Saying which kind, and why, rather than leaving a blank space that
        # reads as a broken page. Most General mail is berthing reports, RPA
        # notices and greetings that nobody replies to, and answering spam is
        # never the right move.
        why = {
            "GENERAL": (
                "General mail is triaged, not answered — these are notices, "
                "reports and acknowledgements that need no reply"
            ),
            "SPAM": "spam is never replied to",
        }.get(result.category, "no reply is drafted for this kind of email")
        return {"draft": None, "why": why}

    try:
        _, email = await asyncio.to_thread(_email_from_source, email_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, detail=f"no such email: {email_id}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, detail=f"The mailbox could not load this email: {exc}")

    provider = build_provider()
    try:
        answered, why = await compose_answer(result, email, get_index(), provider)
    finally:
        await provider.aclose()

    if answered is None:
        return {"draft": None, "why": why}
    return {"draft": answered.as_dict()}


@app_router.post("/inbox/{email_id}/reply/gmail")
async def reply_into_gmail(email_id: str, payload: dict | None = None) -> dict:
    """Put that reply into Gmail as a draft, in the original thread.

    A draft, never a send. The system proposes words; a person presses send.
    """
    from vsmail.gmail import drafts as gmail_drafts
    from vsmail.gmail.client import NotAuthorised, service
    from vsmail.reply import Draft, compose

    result = _results().results.get(email_id)
    if result is None:
        raise HTTPException(404, detail=f"nothing recorded for {email_id}")
    payload = payload or {}
    if payload:
        to = (payload.get("to") or "").strip()
        subject = (payload.get("subject") or "").strip()
        body = (payload.get("body") or "").strip()
        if not (to and subject and body):
            raise HTTPException(422, detail="a draft needs a recipient, a subject and a body")
        draft = Draft(to=to, subject=subject, body=body, kind="edited")
    else:
        # Backward compatible for scripts and older browser builds.
        draft = compose(result)
    if draft is None:
        raise HTTPException(422, detail="there is no reply to write for this email")

    try:
        svc = service()
    except NotAuthorised as exc:
        raise HTTPException(400, detail=str(exc))

    try:
        created = gmail_drafts.create(svc, draft, result.gmail_message_id)
    except Exception as exc:
        raise HTTPException(502, detail=f"Gmail refused the draft: {exc}")
    return {"draft": draft.as_dict(), **created}


@app_router.post("/inbox/{email_id}/reply/send")
async def send_reply_route(email_id: str, payload: dict | None = None) -> dict:
    """Send the reply, as edited on screen.

    The words that go out are the ones in the payload, not the ones we
    composed: a person is allowed to change them, and sending something other
    than what they approved would defeat the approval.

    Where it goes is not theirs to decide by omission. `vsmail.gmail.send`
    refuses unless a test recipient is set or `allow_real` is explicit, and
    that refusal is a 422 here rather than a 500.
    """
    from vsmail.gmail.client import NotAuthorised, service
    from vsmail.gmail.send import RefusedToSend, send_reply
    from vsmail.reply import Draft

    payload = payload or {}
    result = _results().results.get(email_id)
    if result is None:
        raise HTTPException(404, detail=f"nothing recorded for {email_id}")

    to = (payload.get("to") or "").strip()
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    if not (to and subject and body):
        raise HTTPException(422, detail="a reply needs a recipient, a subject and a body")

    draft = Draft(to=to, subject=subject, body=body, kind=payload.get("kind", "edited"))

    try:
        svc = service()
    except NotAuthorised as exc:
        raise HTTPException(400, detail=str(exc))

    try:
        sent = send_reply(
            svc,
            draft,
            result.gmail_message_id,
            supplied_recipient=payload.get("test_recipient"),
            allow_real=bool(payload.get("allow_real")),
        )
    except RefusedToSend as exc:
        raise HTTPException(422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(502, detail=f"Gmail refused to send: {exc}")

    # Replied to, so it leaves the queue. Only a real send does this: a saved
    # draft has not answered anybody.
    _results().mark_sent(email_id)
    return sent


@app_router.get("/inbox/{email_id}/email")
async def incoming_email(email_id: str) -> dict:
    """The email being replied to.

    Read through the source rather than stored: putting 520 bodies into
    results.json would duplicate the bundle and go stale the moment a Gmail
    message changes.

    Both bodies are returned. `core_body` is the trimmed request the
    classifier actually saw; the full text is what a person needs when they
    suspect the trim dropped something.
    """
    try:
        _, email = await asyncio.to_thread(_email_from_source, email_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, detail=f"no such email: {email_id}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, detail=f"The mailbox could not load this email: {exc}")

    result = _results().results.get(email_id)
    slots = attachment_slots(email.attachments)
    roles = {path: role for role, path in slots.items()}
    return {
        "email_id": email_id,
        "sender": email.sender,
        "subject": email.subject,
        "body": email.body,
        "core_body": email.core_body,
        "attachments": [str(a) for a in email.attachments],
        "documents": [
            {
                "path": str(path),
                "name": attachment_name(path),
                "role": roles.get(path),
            }
            for path in email.attachments
        ],
        # What was actually read out of each slot, so the filenames are not
        # the only thing a reviewer has to go on.
        "si_source": result.si_source if result else None,
        "bl_source": result.bl_source if result else None,
    }


def _document_from_source(email_id: str, role: str) -> tuple[str, bytes]:
    """Read one known SI/BL attachment without accepting a path from the URL."""
    source, email = _email_from_source(email_id)
    path = email.attachment_for(role)
    if path is None:
        raise FileNotFoundError(f"no {role} document for {email_id}")
    return path, source.read_bytes(path)


async def _load_document(email_id: str, role: str) -> tuple[str, bytes]:
    role = role.upper()
    if role not in ("SI", "BL"):
        raise HTTPException(404, detail="document role must be SI or BL")
    try:
        return await asyncio.to_thread(_document_from_source, email_id, role)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, detail=f"no {role} document for {email_id}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, detail=f"The document could not be loaded: {exc}")


def _document_media_type(name: str) -> str:
    """Only mark formats browsers can display without executing attachment HTML."""
    guessed = mimetypes.guess_type(name)[0] or "application/octet-stream"
    safe_inline = {
        "application/pdf",
        "text/plain",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
    }
    return guessed if guessed in safe_inline else "application/octet-stream"


@app_router.get("/inbox/{email_id}/documents/{role}")
async def document_file(email_id: str, role: str) -> Response:
    """Return the original attachment to the authenticated in-page viewer."""
    path, data = await _load_document(email_id, role)
    name = attachment_name(path)
    media_type = _document_media_type(name)
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        },
    )


@app_router.get("/inbox/{email_id}/documents/{role}/preview")
async def document_preview(email_id: str, role: str) -> dict:
    """Describe how to render an attachment and safely extract text formats."""
    path, data = await _load_document(email_id, role)
    name = attachment_name(path)
    extension = Path(name).suffix.lower()
    media_type = _document_media_type(name)

    if extension == ".pdf":
        return {
            "name": name,
            "role": role.upper(),
            "media_type": media_type,
            "mode": "pdf",
            "text": None,
            "error": None,
        }
    if media_type.startswith("image/"):
        return {
            "name": name,
            "role": role.upper(),
            "media_type": media_type,
            "mode": "image",
            "text": None,
            "error": None,
        }

    document = await asyncio.to_thread(read_document, path, data, role.upper())
    can_show_text = extension in (".txt", ".docx", ".xlsx", ".xlsm")
    return {
        "name": name,
        "role": role.upper(),
        "media_type": media_type,
        "mode": "text" if can_show_text and document.readable else "download",
        "text": document.text if can_show_text and document.readable else None,
        "error": document.error if not document.readable else None,
    }


@app_router.get("/stats")
async def stats() -> dict:
    result = _results().stats()
    result["awaiting_review"] = len(_review().queue())
    return result


# -- starting work -------------------------------------------------------
@app_router.post("/jobs/run")
async def start_run(payload: dict | None = None) -> dict:
    """Process the requested number of newest emails in the background.

    A full model run is a couple of minutes, which no browser will wait for,
    so it returns a job to poll.
    """
    payload = payload or {}
    source_name = payload.get("source", "gmail")
    write_labels = bool(payload.get("labels", True))
    requested_limit = payload.get("limit")
    if requested_limit is not None:
        if isinstance(requested_limit, bool) or not isinstance(requested_limit, int):
            raise HTTPException(422, detail="limit must be a whole number")
        if not 1 <= requested_limit <= 1000:
            raise HTTPException(422, detail="limit must be between 1 and 1000")

    async def work(job):
        job.set_phase("reading_mailbox", "Reading the mailbox")
        source = _source(source_name)
        provider = build_provider()
        review = _review()
        # Gmail's Python client is synchronous. Offloading this scan is what
        # lets /jobs/{id} answer while a large mailbox is still loading.
        try:
            if source_name == "gmail":
                # Stop Gmail at the requested count. Fetching the whole mailbox
                # and slicing afterwards wastes quota and is why small demo runs
                # could still hit the per-minute API limit.
                emails = (
                    await asyncio.to_thread(source.emails, requested_limit)
                    if requested_limit is not None
                    else await asyncio.to_thread(source.emails)
                )
            else:
                emails = await asyncio.to_thread(source.emails)
        except BaseException:
            await provider.aclose()
            raise
        if source_name != "gmail" and requested_limit is not None:
            emails = emails[:requested_limit]
        job.total = len(emails)
        job.set_phase("classifying", f"Starting {len(emails)} email(s)")

        phase_labels = {
            "classifying": "Classifying email",
            "reading_documents": "Reading attachments",
            "extracting": "Extracting shipping fields",
            "comparing": "Comparing SI and BL fields",
            "checking_discrepancies": "Checking discrepancies",
        }

        def report_stage(email, phase: str) -> None:
            subject = email.subject.strip() or email.email_id
            if len(subject) > 64:
                subject = f"{subject[:61]}..."
            job.set_phase(
                phase,
                f"{phase_labels.get(phase, phase.replace('_', ' ').title())}: {subject}",
                email.email_id,
            )

        try:
            processed = await pipeline.process_all(
                source,
                provider,
                emails=emails,
                store=review,
                progress=lambda done, total: setattr(job, "done", done),
                stage=report_stage,
            )
        finally:
            await provider.aclose()

        job.set_phase("saving_results", "Saving results")
        records = {e.email_id: e for e in emails}
        gmail_message_ids = (
            {email_id: source.message_id_for(email_id) for email_id in records}
            if source_name == "gmail"
            else None
        )
        _results().record(processed, records, source_name, gmail_message_ids)
        counts = review.sync(processed)

        if write_labels and source_name == "gmail":
            from vsmail.gmail.labels import Labels, labels_for

            job.set_phase("applying_labels", "Applying labels in Gmail")
            writer = Labels(source.service)
            for item in processed:
                message_id = source.message_id_for(item.verdict.email_id)
                if message_id:
                    await asyncio.to_thread(
                        writer.apply,
                        message_id,
                        labels_for(item.verdict.to_submission_entry()),
                    )

        result = submission_module.build([p.verdict for p in processed])
        problems = submission_module.validate(result, list(records))
        job.set_phase(
            "complete",
            f"Done: {len(processed)} processed, {counts['opened']} new case(s)",
        )
        return {
            "processed": len(processed),
            "cases_opened": counts["opened"],
            "cases_reopened": counts.get("reopened", 0),
            "submission_problems": problems,
        }

    return JOBS.start("run", work).as_dict()


@app_router.get("/jobs/running")
async def running_jobs() -> dict:
    """Whatever is in flight right now.

    The page asks on load. Work runs in this process and outlives the tab, so
    a reload used to lose sight of a seed that was still going — the mailbox
    filled up while the screen said nothing was happening.
    """
    return {"jobs": [job.as_dict() for job in JOBS.running()]}


@app_router.get("/jobs")
async def jobs() -> dict:
    return {"jobs": JOBS.all()}


@app_router.get("/jobs/{job_id}")
async def job(job_id: str) -> dict:
    found = JOBS.get(job_id)
    if found is None:
        raise HTTPException(404, detail=f"no job {job_id}")
    return found.as_dict()


# -- connecting the mailbox ----------------------------------------------
#: Authorisations this service started, by the `state` Google will hand back,
#: each holding when it started and its PKCE verifier. In memory on purpose: a
#: restart should invalidate a half-finished consent rather than leave it
#: open, and nothing here outlives one.
_PENDING: dict[str, tuple[float, str | None]] = {}

#: How long a consent may take before its state is no longer accepted.
STATE_TTL = 600.0


def _drop_stale(now: float) -> None:
    for state, (started, _) in list(_PENDING.items()):
        if now - started > STATE_TTL:
            del _PENDING[state]


@app_router.get("/gmail/status")
async def gmail_status() -> dict:
    """Whether Gmail is usable, without throwing if it is not set up.

    The two `*_source` fields exist because "it says it is not connected" is
    otherwise an unanswerable question on a deployment: they say whether the
    client and the token were read from the environment, from a file, or not
    found at all, which turns the diagnosis into one request.
    """
    from vsmail.gmail.client import (
        NotAuthorised,
        address,
        authorised,
        client_config,
        credentials_source,
        service,
        token_source,
    )

    info: dict = {
        "credentials_present": False,
        "credentials_source": credentials_source(),
        "authorised": authorised(),
        "token_source": token_source(),
        "ready": False,
        "expired": False,
        "mailbox": None,
    }

    try:
        client_config()
        info["credentials_present"] = True
    except NotAuthorised as exc:
        # Only worth reporting when something *was* found and could not be
        # used; an absent client is what `credentials_source: null` says.
        if info["credentials_source"] is not None:
            info["error"] = str(exc)
        return info

    if info["authorised"]:
        try:
            info["mailbox"] = await asyncio.to_thread(address, service())
            info["ready"] = True
        except NotAuthorised as exc:
            # The seven-day expiry lands here. The page offers re-consent
            # rather than the setup instructions.
            info["expired"] = True
            info["error"] = str(exc)
        except Exception as exc:
            info["error"] = str(exc)
    return info


@app_router.get("/gmail/auth/start")
async def gmail_auth_start() -> dict:
    """Begin consent. The browser goes where this says.

    Guarded, and that is what makes the unguarded callback safe: the `state`
    it will accept can only be minted here, behind the service token.
    """
    import time

    from vsmail.gmail.client import NotAuthorised, authorization_url

    try:
        url, state, verifier = authorization_url()
    except NotAuthorised as exc:
        raise HTTPException(400, detail=str(exc))
    except Exception as exc:
        # Anything else is still a setup problem from where the operator sits,
        # and a bare 500 tells them nothing about which value to go and look at.
        raise HTTPException(400, detail=f"Gmail could not be set up: {exc}")

    now = time.time()
    _drop_stale(now)
    _PENDING[state] = (now, verifier)
    return {"authorization_url": url}


@oauth_router.get("/gmail/auth/callback", include_in_schema=False)
async def gmail_auth_callback(
    code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Where Google returns the operator after they approve.

    Unauthenticated by necessity — this is a browser redirect, so there is no
    place to put the service token. `state` carries the guard instead: it was
    issued by the guarded start route and is single-use, so a request that
    did not come from a real authorisation has nothing to present.

    The result is a redirect rather than JSON because a person is looking at
    it. The token itself is never rendered.

    It lands back on #/gmail rather than the root: consent leaves the app
    entirely, and returning somebody to the inbox after they pressed Connect
    on the Gmail screen loses their place at the one moment they are looking
    for confirmation.
    """
    import time

    from vsmail.gmail.client import NotAuthorised, exchange

    if error:
        return RedirectResponse(f"/?gmail=denied&detail={error}#/gmail")

    # Prune first, then look: otherwise the state being presented is popped
    # without its own age ever being checked, and an authorisation started
    # hours ago still completes.
    _drop_stale(time.time())
    pending = _PENDING.pop(state, None)
    if pending is None:
        return RedirectResponse("/?gmail=expired#/gmail")

    try:
        exchange(code, state, pending[1])
    except NotAuthorised as exc:
        return RedirectResponse(f"/?gmail=denied&detail={exc}#/gmail")
    except Exception:
        return RedirectResponse("/?gmail=failed#/gmail")
    return RedirectResponse("/?gmail=connected#/gmail")


@app_router.post("/gmail/seed")
async def gmail_seed(payload: dict | None = None) -> dict:
    limit = (payload or {}).get("limit")
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise HTTPException(422, detail="limit must be a whole number")
        if not 1 <= limit <= 1000:
            raise HTTPException(422, detail="limit must be between 1 and 1000")

    async def work(job):
        from vsmail.gmail import seed as seeding
        from vsmail.gmail.client import service

        svc = service()
        job.total = limit or len(Bundle().emails())
        job.set_phase("loading_samples", "Loading sample emails into Gmail")
        # The seeder is synchronous and rate-limited; a thread keeps the
        # event loop free so progress can still be polled.
        def progress(done: int, total: int) -> None:
            # Called from the seeder's thread. An int assignment is all this
            # is, and the page polls rather than being pushed to.
            job.done = done
            job.total = total

        result = await asyncio.to_thread(seeding.seed, svc, None, limit, progress)
        job.done = result["inserted"] + result["skipped"] + len(result["failed"])
        summary = f"inserted {result['inserted']} into {result['mailbox']}"
        if result["skipped"]:
            summary += f"; {result['skipped']} already present"
        if result["failed"]:
            summary += f"; {len(result['failed'])} failed"
        job.say(summary)
        return result

    return JOBS.start("seed", work).as_dict()


@app_router.post("/gmail/disconnect")
async def gmail_disconnect() -> dict:
    """Detach the mailbox, revoking the grant at Google.

    Connect had no counterpart, so unhooking a mailbox meant editing a
    Railway variable or waiting out the seven-day expiry.
    """
    from vsmail.gmail.client import forget

    return forget()


@app_router.post("/gmail/reset")
async def gmail_reset(payload: dict | None = None) -> dict:
    """Bin the seeded messages, and optionally forget the run as well.

    `also_results` defaults to false so `scripts/` keeps its old behaviour.
    The page sends true, because clearing the mailbox while leaving all 520
    results on screen is "clear" doing half of what it says.
    """
    payload = payload or {}
    also_results = bool(payload.get("also_results"))

    async def work(job):
        import asyncio

        from vsmail.gmail import seed as seeding
        from vsmail.gmail.client import NotAuthorised, service

        result: dict = {"trashed": 0, "mailbox": False}
        try:
            svc = service()
        except NotAuthorised:
            # Nothing to bin. Clearing the screen should still work, so this
            # is not an error — a run from the bundle has no mailbox behind it.
            job.say("no mailbox connected; nothing to bin")
        else:
            job.say("moving seeded messages to the bin")
            binned = await asyncio.to_thread(seeding.reset, svc)
            result = {**binned, "mailbox": True}
            job.say(f"binned {binned['trashed']}")

        if also_results:
            job.say("clearing the last run")
            result["results_cleared"] = _results().clear()
        return result

    return JOBS.start("reset", work).as_dict()


# -- watching for live mail ---------------------------------------------
@app_router.post("/watch/start")
async def watch_start(payload: dict | None = None) -> dict:
    """Poll the mailbox and process whatever arrives."""
    payload = payload or {}
    interval = float(payload.get("interval", 10))
    write_labels = payload.get("labels", True)

    async def work(job):
        from vsmail.gmail.client import address, service
        from vsmail.gmail.labels import Labels, labels_for
        from vsmail.gmail.source import GmailSource

        svc = service()
        source = GmailSource(svc)
        labels = Labels(svc)
        provider = build_provider()
        review = _review()
        results = _results()

        try:
            seen = set(await asyncio.to_thread(source.message_ids))
            mailbox = await asyncio.to_thread(address, svc)
            job.set_phase(
                "monitoring",
                f"watching {mailbox} — {len(seen)} existing message(s) ignored",
            )
            while True:
                await asyncio.sleep(interval)
                listed = await asyncio.to_thread(source.message_ids)
                fresh = [m for m in listed if m not in seen]
                for message_id in fresh:
                    record = await asyncio.to_thread(source.get_message, message_id)
                    processed = await pipeline.process_email(
                        source, provider, record, store=review
                    )
                    entry = processed.verdict.to_submission_entry()
                    results.record(
                        [processed],
                        {record.email_id: record},
                        "gmail",
                        {record.email_id: message_id},
                    )
                    review.sync([processed])
                    if write_labels:
                        await asyncio.to_thread(
                            labels.apply, message_id, labels_for(entry)
                        )
                    seen.add(message_id)
                    job.done += 1
                    job.say(
                        f"{record.subject[:60] or '(no subject)'} -> "
                        f"{entry['category']} {entry['status']}"
                    )
        finally:
            await provider.aclose()

    return JOBS.start("watch", work).as_dict()


@app_router.post("/watch/stop")
async def watch_stop() -> dict:
    return {"stopped": JOBS.stop("watch")}


@app_router.get("/watch/status")
async def watch_status() -> dict:
    job = JOBS.latest("watch")
    return {"watching": bool(job and job.state == RUNNING), "job": job.as_dict() if job else None}
