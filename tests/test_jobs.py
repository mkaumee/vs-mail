"""Background work, which a browser polls rather than waits for."""
import asyncio

from vsmail.jobs import DONE, FAILED, STOPPED, Jobs


async def test_a_job_reports_progress_and_finishes():
    jobs = Jobs()

    async def work(job):
        job.total = 3
        for step in range(3):
            job.done = step + 1
            job.say(f"step {step + 1}")
            await asyncio.sleep(0)
        return {"ok": True}

    job = jobs.start("demo", work)
    await asyncio.sleep(0.05)
    assert job.state == DONE
    assert (job.done, job.total) == (3, 3)
    assert job.result == {"ok": True}


async def test_a_failure_is_reported_rather_than_swallowed():
    jobs = Jobs()

    async def work(job):
        raise ValueError("no mailbox")

    job = jobs.start("demo", work)
    await asyncio.sleep(0.05)
    assert job.state == FAILED
    assert "no mailbox" in job.error


async def test_only_one_of_a_kind_runs_at_a_time():
    """Two seeds at once would insert the whole dataset twice."""
    jobs = Jobs()

    async def work(job):
        await asyncio.sleep(0.2)

    first = jobs.start("seed", work)
    second = jobs.start("seed", work)
    assert first.id == second.id
    jobs.stop("seed")


async def test_a_long_running_job_can_be_stopped():
    jobs = Jobs()

    async def forever(job):
        while True:
            await asyncio.sleep(0.01)

    jobs.start("watch", forever)
    await asyncio.sleep(0.02)
    assert jobs.stop("watch")
    await asyncio.sleep(0.05)
    assert jobs.latest("watch").state == STOPPED


async def test_stopping_something_not_running_says_so():
    assert Jobs().stop("watch") is False


async def test_the_log_is_capped():
    """A watcher left running for hours must not grow without bound."""
    jobs = Jobs()

    async def work(job):
        for index in range(500):
            job.say(f"line {index}", keep=50)

    job = jobs.start("demo", work)
    await asyncio.sleep(0.05)
    assert len(job.log) == 50


def test_running_reports_what_is_in_flight():
    """Work outlives the tab that started it. A reloaded page asks for this
    and adopts what it finds, instead of showing an idle screen while the
    mailbox fills up behind it."""
    import asyncio

    from vsmail.jobs import Jobs

    async def scenario():
        jobs = Jobs()
        gate = asyncio.Event()

        async def slow(job):
            await gate.wait()
            return {"ok": True}

        async def quick(job):
            return {"ok": True}

        started = jobs.start("seed", slow)
        jobs.start("run", quick)
        await asyncio.sleep(0)  # let `quick` finish

        in_flight = [j.id for j in jobs.running()]
        gate.set()
        await asyncio.sleep(0)
        return started.id, in_flight

    started_id, in_flight = asyncio.run(scenario())
    assert in_flight == [started_id]
