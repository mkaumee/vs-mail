"""Work that takes longer than a web request.

Seeding a mailbox takes about a minute, a full model run a couple of
minutes. A browser cannot wait for either, so they run in the background and
the page polls for progress.

In-process and single-worker by design: this serves one ops desk, and a task
queue would be more machinery than the problem deserves.
"""
from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone

RUNNING = "running"
DONE = "done"
FAILED = "failed"
STOPPED = "stopped"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: str
    state: str = RUNNING
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    #: Free text the page shows while it waits.
    message: str = ""
    done: int = 0
    total: int = 0
    result: dict | None = None
    error: str | None = None
    #: Lines a long job produces as it goes, so a watcher can stream.
    log: list = field(default_factory=list)

    def say(self, line: str, keep: int = 200) -> None:
        self.log.append({"at": _now(), "line": line})
        del self.log[:-keep]
        self.message = line

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "done": self.done,
            "total": self.total,
            "result": self.result,
            "error": self.error,
            "log": self.log[-50:],
        }


class Jobs:
    """Everything running or recently finished."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._counter = 0

    def start(self, kind: str, work) -> Job:
        """Run `work(job)` in the background. One of each kind at a time."""
        existing = self.latest(kind)
        if existing and existing.state == RUNNING:
            return existing

        self._counter += 1
        job = Job(id=f"{kind}-{self._counter}", kind=kind)
        self._jobs[job.id] = job

        async def runner():
            try:
                job.result = await work(job)
                job.state = DONE if job.state == RUNNING else job.state
            except asyncio.CancelledError:
                job.state = STOPPED
                job.say("stopped")
                raise
            except Exception as exc:
                job.state = FAILED
                job.error = f"{type(exc).__name__}: {exc}"
                job.say(job.error)
                traceback.print_exc()
            finally:
                job.finished_at = _now()

        self._tasks[job.id] = asyncio.create_task(runner())
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def latest(self, kind: str) -> Job | None:
        matching = [j for j in self._jobs.values() if j.kind == kind]
        return matching[-1] if matching else None

    def stop(self, kind: str) -> bool:
        job = self.latest(kind)
        if not job or job.state != RUNNING:
            return False
        task = self._tasks.get(job.id)
        if task:
            task.cancel()
        return True

    def running(self) -> list[Job]:
        """Whatever is in flight.

        Work outlives the tab that started it, so a reloaded page asks for
        this and adopts what it finds — otherwise a seed carries on filling
        the mailbox while the screen says nothing is happening.
        """
        return [job for job in self._jobs.values() if job.state == RUNNING]

    def all(self) -> list[dict]:
        return [job.as_dict() for job in self._jobs.values()]


#: One registry for the process.
JOBS = Jobs()
