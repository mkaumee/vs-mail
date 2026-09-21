"""Release processing uses the server configuration, including from stale tabs."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import app_routes, routes
from api.main import app
from vsmail.jobs import Jobs
from vsmail.results import ResultStore


@pytest.mark.parametrize("limit", [True, 0, -1, 1001, "10", 2.5])
async def test_run_rejects_an_invalid_email_limit(limit):
    with pytest.raises(HTTPException) as error:
        await app_routes.start_run({"limit": limit})
    assert error.value.status_code == 422


@pytest.mark.parametrize("limit", [True, 0, -1, 1001, "10", 2.5])
async def test_sample_load_rejects_an_invalid_email_limit(limit):
    with pytest.raises(HTTPException) as error:
        await app_routes.gmail_seed({"limit": limit})
    assert error.value.status_code == 422


async def test_run_passes_the_selected_limit_to_gmail(monkeypatch, tmp_path):
    seen = []

    class Mailbox:
        service = object()

        def emails(self, limit=None):
            seen.append(limit)
            return []

    class Provider:
        async def aclose(self):
            pass

    jobs = Jobs()
    monkeypatch.setattr(app_routes, "JOBS", jobs)
    monkeypatch.setattr(app_routes, "_source", lambda name: Mailbox())
    monkeypatch.setattr(app_routes, "build_provider", lambda: Provider())
    monkeypatch.setenv("VS_RESULTS_STORE", str(tmp_path / "results.json"))
    monkeypatch.setenv("VS_REVIEW_STORE", str(tmp_path / "review.json"))

    response = await app_routes.start_run(
        {"source": "gmail", "limit": 25, "labels": False}
    )
    await jobs._tasks[response["id"]]

    assert jobs.get(response["id"]).state == "done"
    assert seen == [25]


def test_service_defaults_to_live_processing(monkeypatch):
    monkeypatch.delenv("VS_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert routes.provider_name() == "deepseek"
    assert TestClient(app).get("/health").json()["provider"] == "deepseek"
    # Missing credentials must not quietly produce offline results.
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        routes.build_provider()


def test_unknown_provider_does_not_fall_back_to_offline(monkeypatch):
    monkeypatch.setenv("VS_PROVIDER", "misspelled")
    with pytest.raises(HTTPException) as error:
        routes.build_provider()
    assert error.value.status_code == 503


@pytest.mark.parametrize("provider_name", ["deepseek", "remote"])
@pytest.mark.parametrize("kind", ["run", "watch"])
@pytest.mark.parametrize("payload", [{}, {"provider": "mock"}])
async def test_jobs_use_the_server_provider(monkeypatch, tmp_path, provider_name, kind, payload):
    from vsmail.gmail import client, labels, source
    from vsmail.llm import deepseek, remote

    monkeypatch.setenv("VS_PROVIDER", provider_name)
    monkeypatch.setenv("VS_RESULTS_STORE", str(tmp_path / "results.json"))
    monkeypatch.setenv("VS_REVIEW_STORE", str(tmp_path / "review.json"))
    jobs = Jobs()
    monkeypatch.setattr(app_routes, "JOBS", jobs)
    chosen = []

    class Provider:
        aclose = AsyncMock()

        def __init__(self):
            chosen.append(provider_name)

    monkeypatch.setattr(deepseek if provider_name == "deepseek" else remote,
                        "DeepSeekProvider" if provider_name == "deepseek" else "RemoteProvider",
                        Provider)

    class Mailbox:
        def __init__(self, service=None):
            self.service = service

        def emails(self):
            return []

        def message_ids(self):
            return []

    monkeypatch.setattr(client, "service", lambda: object())
    monkeypatch.setattr(client, "address", lambda service: "judge@example.com")
    monkeypatch.setattr(source, "GmailSource", Mailbox)
    monkeypatch.setattr(labels, "Labels", lambda service: object())

    response = await (app_routes.start_run(payload) if kind == "run"
                      else app_routes.watch_start(payload))
    task = jobs._tasks[response["id"]]
    try:
        if kind == "run":
            await task
            assert jobs.get(response["id"]).state == "done"
            assert ResultStore(tmp_path / "results.json").source == "gmail"
        else:
            await asyncio.sleep(0)
            assert jobs.get(response["id"]).state == "running"
        assert chosen == [provider_name]
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    Provider.aclose.assert_awaited_once()


def test_existing_results_are_read_from_their_original_source(monkeypatch, tmp_path):
    monkeypatch.delenv("VS_RESULT_SOURCE", raising=False)
    path = tmp_path / "results.json"
    monkeypatch.setenv("VS_RESULTS_STORE", str(path))
    assert app_routes._result_source() == "gmail"
    store = ResultStore(path)
    for source in ("gmail", "bundle"):
        store.source = source
        store.save()
        assert app_routes._result_source() == source
