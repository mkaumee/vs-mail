"""Everything the browser talks to.

The existing routes serve the pipeline. These serve the app: an inbox to
look at, buttons that start work, and progress to watch while it runs.
"""
from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_token
from vsmail import pipeline, submission as submission_module
from vsmail.inbox import Bundle
from vsmail.jobs import JOBS, RUNNING
from vsmail.results import ResultStore
from vsmail.review import ReviewStore

app_router = APIRouter(dependencies=[Depends(require_token)])


def _results() -> ResultStore:
    return ResultStore(os.environ.get("VS_RESULTS_STORE", "results.json"))


def _review() -> ReviewStore:
    return ReviewStore(os.environ.get("VS_REVIEW_STORE", "review.json"))


def _provider(name: str):
    if name == "deepseek":
        from vsmail.llm.deepseek import DeepSeekProvider

        return DeepSeekProvider()
    if name == "remote":
        from vsmail.llm.remote import RemoteProvider

        return RemoteProvider()
    from vsmail.llm.mock import MockProvider

    return MockProvider()


def _source(name: str):
    """A bundle folder or a real mailbox, behind the same three methods."""
    if name == "gmail":
        from vsmail.gmail.client import service
        from vsmail.gmail.source import GmailSource

        return GmailSource(service())
    return Bundle() if name in ("", "bundle") else Bundle(name)


# -- looking at the inbox ------------------------------------------------
@app_router.get("/inbox")
async def inbox() -> dict:
    """The mailbox as lanes, comparison requests first.

    Sorting one long list by arrival buries the work. The lane that matters
    is the one holding documents to check.
    """
    store = _results()
    return {
        "stats": store.stats(),
        "lanes": {
            name: [asdict(r) for r in items]
            for name, items in store.lanes().items()
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


@app_router.get("/stats")
async def stats() -> dict:
    return _results().stats()


# -- starting work -------------------------------------------------------
@app_router.post("/jobs/run")
async def start_run(payload: dict | None = None) -> dict:
    """Process the whole inbox in the background.

    A full model run is a couple of minutes, which no browser will wait for,
    so it returns a job to poll.
    """
    payload = payload or {}
    source_name = payload.get("source", "bundle")
    provider_name = payload.get("provider", "mock")
    write_labels = bool(payload.get("labels"))

    async def work(job):
        job.say(f"reading {source_name}")
        source = _source(source_name)
        provider = _provider(provider_name)
        review = _review()
        emails = source.emails()
        job.total = len(emails)
        job.say(f"{len(emails)} email(s); running {provider_name}")

        try:
            processed = await pipeline.process_all(
                source,
                provider,
                emails=emails,
                store=review,
                progress=lambda done, total: setattr(job, "done", done),
            )
        finally:
            await provider.aclose()

        records = {e.email_id: e for e in emails}
        _results().record(processed, records, source_name)
        counts = review.sync(processed)

        if write_labels and source_name == "gmail":
            from vsmail.gmail.labels import Labels, labels_for

            job.say("writing labels back to Gmail")
            writer = Labels(source.service)
            for item in processed:
                message_id = source.message_id_for(item.verdict.email_id)
                if message_id:
                    writer.apply(
                        message_id, labels_for(item.verdict.to_submission_entry())
                    )

        result = submission_module.build([p.verdict for p in processed])
        problems = submission_module.validate(result, list(records))
        job.say(f"done: {len(processed)} processed, {counts['opened']} new case(s)")
        return {
            "processed": len(processed),
            "cases_opened": counts["opened"],
            "cases_reopened": counts.get("reopened", 0),
            "submission_problems": problems,
        }

    return JOBS.start("run", work).as_dict()


@app_router.get("/jobs")
async def jobs() -> dict:
    return {"jobs": JOBS.all()}


@app_router.get("/jobs/{job_id}")
async def job(job_id: str) -> dict:
    found = JOBS.get(job_id)
    if found is None:
        raise HTTPException(404, detail=f"no job {job_id}")
    return found.as_dict()


# -- the mailbox itself --------------------------------------------------
@app_router.get("/gmail/status")
async def gmail_status() -> dict:
    """Whether Gmail is usable, without throwing if it is not set up."""
    from vsmail.gmail.client import CREDENTIALS, TOKEN

    ready = CREDENTIALS.is_file() and TOKEN.is_file()
    info: dict = {
        "credentials_present": CREDENTIALS.is_file(),
        "authorised": TOKEN.is_file(),
        "ready": ready,
        "mailbox": None,
    }
    if ready:
        try:
            from vsmail.gmail.client import address, service

            info["mailbox"] = address(service(interactive=False))
        except Exception as exc:
            info["ready"] = False
            info["error"] = str(exc)
    return info


@app_router.post("/gmail/seed")
async def gmail_seed(payload: dict | None = None) -> dict:
    limit = (payload or {}).get("limit")

    async def work(job):
        from vsmail.gmail import seed as seeding
        from vsmail.gmail.client import service

        svc = service(interactive=False)
        job.total = limit or len(Bundle().emails())
        job.say("inserting messages")
        # The seeder is synchronous and rate-limited; a thread keeps the
        # event loop free so progress can still be polled.
        import asyncio

        result = await asyncio.to_thread(seeding.seed, svc, None, limit)
        job.done = result["inserted"]
        job.say(f"inserted {result['inserted']} into {result['mailbox']}")
        return result

    return JOBS.start("seed", work).as_dict()


@app_router.post("/gmail/reset")
async def gmail_reset() -> dict:
    async def work(job):
        import asyncio

        from vsmail.gmail import seed as seeding
        from vsmail.gmail.client import service

        job.say("moving seeded messages to the bin")
        result = await asyncio.to_thread(seeding.reset, service(interactive=False))
        job.say(f"binned {result['trashed']}")
        return result

    return JOBS.start("reset", work).as_dict()


# -- watching for live mail ---------------------------------------------
@app_router.post("/watch/start")
async def watch_start(payload: dict | None = None) -> dict:
    """Poll the mailbox and process whatever arrives."""
    payload = payload or {}
    interval = float(payload.get("interval", 10))
    provider_name = payload.get("provider", "mock")
    write_labels = payload.get("labels", True)

    async def work(job):
        import asyncio

        from vsmail.gmail.client import address, service
        from vsmail.gmail.labels import Labels, labels_for
        from vsmail.gmail.message import to_record
        from vsmail.gmail.source import GmailSource

        svc = service(interactive=False)
        source = GmailSource(svc)
        labels = Labels(svc)
        provider = _provider(provider_name)
        review = _review()
        results = _results()

        seen = set(source.message_ids())
        job.say(f"watching {address(svc)} — {len(seen)} existing message(s) ignored")

        try:
            while True:
                await asyncio.sleep(interval)
                fresh = [m for m in source.message_ids() if m not in seen]
                for message_id in fresh:
                    record = to_record(source._message(message_id))
                    processed = await pipeline.process_email(
                        source, provider, record, store=review
                    )
                    entry = processed.verdict.to_submission_entry()
                    results.record([processed], {record.email_id: record}, "gmail")
                    review.sync([processed])
                    if write_labels:
                        labels.apply(message_id, labels_for(entry))
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
