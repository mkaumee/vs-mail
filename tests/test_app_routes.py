"""The endpoints the browser calls."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from api.main import app

TOKEN = "test-token"


@pytest.fixture
def client(monkeypatch, tmp_path, bundle):
    """A client whose stores are seeded from a real run."""
    from vsmail import pipeline
    from vsmail.llm.mock import MockProvider
    from vsmail.results import ResultStore
    from vsmail.review import ReviewStore

    processed = asyncio.run(pipeline.process_all(bundle, MockProvider()))
    results = ResultStore(tmp_path / "results.json")
    results.record(processed, {e.email_id: e for e in bundle.emails()}, "bundle")
    ReviewStore(tmp_path / "review.json").sync(processed)

    monkeypatch.setenv("VS_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("VS_PROVIDER", "mock")
    monkeypatch.setenv("VS_RESULTS_STORE", str(tmp_path / "results.json"))
    monkeypatch.setenv("VS_REVIEW_STORE", str(tmp_path / "review.json"))
    return TestClient(app)


@pytest.fixture
def auth():
    return {"X-VS-Token": TOKEN}


def test_the_app_is_served_at_the_root(client):
    """One URL for the page and the API, so there is no CORS to configure."""
    response = client.get("/")
    assert response.status_code == 200
    assert "<div id=\"root\">" in response.text


def test_the_page_does_not_shadow_an_api_route(client):
    assert client.get("/health").json()["status"] == "ok"


def test_the_inbox_needs_a_token(client):
    assert client.get("/inbox").status_code == 401


def test_the_inbox_comes_back_as_lanes(client, auth):
    body = client.get("/inbox", headers=auth).json()
    assert body["stats"]["total"] == 520
    assert len(body["lanes"]["BL_COMPARISON"]) == 129
    assert body["lanes"]["BL_COMPARISON"][0]["status"] == "MISMATCH"


def test_an_email_carries_its_field_detail(client, auth):
    body = client.get("/inbox/email_004", headers=auth).json()
    assert body["result"]["defect_fields"] == ["consignee", "notify_party"]
    assert len(body["result"]["fields"]) == 7


def test_an_email_carries_its_review_case(client, auth):
    body = client.get("/inbox/email_501", headers=auth).json()
    assert body["case"]["reason"] == "wrong_doc_type"


def test_an_unknown_email_is_a_404(client, auth):
    assert client.get("/inbox/email_999", headers=auth).status_code == 404


def test_stats_are_available_on_their_own(client, auth):
    stats = client.get("/stats", headers=auth).json()
    assert stats["defects_found"] == 46
    assert stats["awaiting_review"] >= 1


def test_a_run_returns_a_job_rather_than_blocking(client, auth):
    """A full model run is minutes; no browser waits for that."""
    job = client.post(
        "/jobs/run", json={"source": "bundle", "provider": "mock"}, headers=auth
    ).json()
    assert job["kind"] == "run"
    assert job["state"] in ("running", "done")
    assert client.get(f"/jobs/{job['id']}", headers=auth).status_code == 200


def test_an_unknown_job_is_a_404(client, auth):
    assert client.get("/jobs/nope-1", headers=auth).status_code == 404


def test_gmail_status_answers_even_when_unconfigured(client, auth, monkeypatch, tmp_path):
    """The page asks on load; it must not blow up before setup is done."""
    from vsmail.gmail import client as gmail_client

    monkeypatch.setattr(gmail_client, "CREDENTIALS", tmp_path / "nope.json")
    monkeypatch.setattr(gmail_client, "TOKEN", tmp_path / "nope-token.json")
    body = client.get("/gmail/status", headers=auth).json()
    assert body["ready"] is False
    assert body["credentials_present"] is False


def test_watch_reports_that_it_is_not_running(client, auth):
    assert client.get("/watch/status", headers=auth).json()["watching"] is False


def test_stopping_a_watcher_that_is_not_running_is_not_an_error(client, auth):
    assert client.post("/watch/stop", headers=auth).json() == {"stopped": False}
