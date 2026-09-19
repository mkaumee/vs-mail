"""The service — routing, the auth guard, and that it reuses the pipeline."""
import base64

import pytest
from fastapi.testclient import TestClient

from api.main import app

TOKEN = "test-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("VS_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("VS_PROVIDER", "mock")
    return TestClient(app)


@pytest.fixture
def auth():
    return {"X-VS-Token": TOKEN}


def test_health_needs_no_token(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_whether_the_guard_is_configured(client):
    assert client.get("/health").json()["token_configured"] is True


def test_a_missing_token_is_rejected(client):
    assert client.post("/classify", json={"body": "hello"}).status_code == 401


def test_a_wrong_token_is_rejected(client):
    response = client.post(
        "/classify", json={"body": "hello"}, headers={"X-VS-Token": "nope"}
    )
    assert response.status_code == 401


def test_routes_fail_closed_when_no_token_is_configured(monkeypatch):
    """An unguarded model endpoint would be drained, so it refuses to serve."""
    monkeypatch.delenv("VS_SERVICE_TOKEN", raising=False)
    response = TestClient(app).post(
        "/classify", json={"body": "hello"}, headers={"X-VS-Token": "anything"}
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_classify_returns_a_category(client, auth):
    response = client.post(
        "/classify",
        json={"body": "Please compare the SI and draft BL for X and confirm."},
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["category"] == "BL_COMPARISON"


def test_compare_returns_a_verdict_and_the_field_detail(client, auth, bundle):
    email = bundle.get("email_004")
    si_path, bl_path = email.attachment_for("SI"), email.attachment_for("BL")
    payload = {
        "email_id": "email_004",
        "si": {
            "path": si_path,
            "role": "SI",
            "text": bundle.read_bytes(si_path).decode(),
        },
        "bl": {
            "path": bl_path,
            "role": "BL",
            "text": bundle.read_bytes(bl_path).decode(),
        },
    }
    body = client.post("/compare", json=payload, headers=auth).json()
    assert body["verdict"]["status"] == "MISMATCH"
    assert body["verdict"]["defect_fields"] == ["consignee", "notify_party"]
    assert len(body["fields"]) == 7
    assert {f["field"] for f in body["fields"] if not f["equal"]} == {
        "consignee",
        "notify_party",
    }


def test_compare_accepts_base64_pages(client, auth, bundle):
    """Scans travel as base64 PNG, the same way the remote provider sends them."""
    from vsmail.documents import read_document

    path = "attachments/email_512_SI.pdf"
    document = read_document(path, bundle.read_bytes(path))
    encoded = [base64.b64encode(image).decode() for image in document.images]
    payload = {
        "si": {"path": path, "role": "SI", "text": "", "images": encoded},
        "bl": {"path": path, "role": "BL", "text": "", "images": encoded},
    }
    response = client.post("/compare", json=payload, headers=auth)
    assert response.status_code == 200
    # The offline provider cannot read an image, so it escalates rather than guesses.
    assert response.json()["verdict"]["review_reason"] == "missing_value"


def test_submit_scores_against_the_devset_and_says_so(client, auth):
    import asyncio

    from vsmail import pipeline, submission as sub
    from vsmail.inbox import Bundle
    from vsmail.llm.mock import MockProvider

    verdicts = asyncio.run(pipeline.run(Bundle(), MockProvider()))
    response = client.post(
        "/submit", json={"submission": sub.build(verdicts)}, headers=auth
    )
    body = response.json()
    assert "devset_score" in body
    assert "final_score" not in body, "this scorer must never claim to be the real one"
    assert "not ground truth" in body["note"]
