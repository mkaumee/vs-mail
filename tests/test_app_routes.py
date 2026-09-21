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


def test_help_lane_contains_open_human_review_cases_without_changing_category(
    client, auth
):
    body = client.get("/inbox", headers=auth).json()
    help_rows = body["lanes"]["HELP"]

    assert help_rows
    assert len(help_rows) == body["stats"]["awaiting_review"]
    assert "email_501" in {row["email_id"] for row in help_rows}
    assert all(row["category"] != "HELP" for row in help_rows)


def test_confirming_human_review_removes_it_from_help_but_not_its_real_lane(
    client, auth
):
    before = client.get("/inbox", headers=auth).json()
    before_count = before["stats"]["awaiting_review"]

    response = client.post(
        "/review/email_501/resolve",
        headers=auth,
        json={"by": "reviewer", "confirm": True},
    )
    assert response.status_code == 200

    after = client.get("/inbox", headers=auth).json()
    assert "email_501" not in {row["email_id"] for row in after["lanes"]["HELP"]}
    assert "email_501" in {
        row["email_id"] for row in after["lanes"]["BL_COMPARISON"]
    }
    assert after["stats"]["awaiting_review"] == before_count - 1


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

    monkeypatch.delenv(gmail_client.TOKEN_ENV, raising=False)
    monkeypatch.setattr(gmail_client, "CREDENTIALS", tmp_path / "nope.json")
    monkeypatch.setattr(gmail_client, "TOKEN", tmp_path / "nope-token.json")
    body = client.get("/gmail/status", headers=auth).json()
    assert body["ready"] is False
    assert body["credentials_present"] is False


def test_watch_reports_that_it_is_not_running(client, auth):
    assert client.get("/watch/status", headers=auth).json()["watching"] is False


def test_stopping_a_watcher_that_is_not_running_is_not_an_error(client, auth):
    assert client.post("/watch/stop", headers=auth).json() == {"stopped": False}


# -- resolving has to become visible -------------------------------------
def test_a_resolution_is_invisible_until_the_email_is_rechecked(client, auth):
    """The bug this pins was only findable by using the app.

    `resolve` records a value and deliberately does not write a verdict — the
    comparator has to run again over it. Nothing did, so the page kept showing
    what the original run stored and a reviewer supplying a correct value saw
    absolutely nothing happen.
    """
    before = client.get("/inbox/email_516", headers=auth).json()["result"]
    assert before["status"] == "NEEDS_REVIEW"
    assert before["review_reason"] == "missing_value"

    client.post(
        "/review/email_516/resolve",
        headers=auth,
        json={"by": "test", "si": {"gross_weight_kg": "235,550 KG"}},
    )
    # Recording alone changes nothing the page can see.
    assert client.get("/inbox/email_516", headers=auth).json()["result"]["status"] == (
        "NEEDS_REVIEW"
    )

    assert client.post("/inbox/email_516/recheck", headers=auth).status_code == 200
    after = client.get("/inbox/email_516", headers=auth).json()["result"]
    assert after["status"] == "OK"
    assert any("corrected by a reviewer" in p for p in after["provenance"])


def test_a_wrong_supplied_value_is_compared_not_accepted(client, auth):
    """A reviewer supplies an input, never a verdict."""
    client.post(
        "/review/email_516/resolve",
        headers=auth,
        json={"by": "test", "si": {"gross_weight_kg": "999 KG"}},
    )
    client.post("/inbox/email_516/recheck", headers=auth)
    result = client.get("/inbox/email_516", headers=auth).json()["result"]
    assert result["status"] == "MISMATCH"
    assert result["defect_fields"] == ["gross_weight_kg"]


def test_rechecking_an_unknown_email_is_a_404(client, auth):
    assert client.post("/inbox/nope/recheck", headers=auth).status_code == 404


def test_a_recheck_does_not_pretend_the_whole_inbox_was_rerun(client, auth):
    """`ran_at` describes the run that produced the other 519 rows. A single
    retry restamping it would make the whole table look fresher than it is."""
    before = client.get("/stats", headers=auth).json()
    client.post("/inbox/email_516/recheck", headers=auth)
    after = client.get("/stats", headers=auth).json()
    assert after["ran_at"] == before["ran_at"]
    assert after["total"] == before["total"]


# -- the drafted reply ----------------------------------------------------
def test_a_comparison_gets_a_drafted_reply(client, auth):
    body = client.get("/inbox/email_004/reply", headers=auth).json()
    draft = body["draft"]
    assert draft["kind"] == "mismatch"
    assert draft["to"] == "docs@vitalsolutions.sg"
    assert draft["subject"].startswith("RE: ")
    assert "Kindly amend the draft" in draft["body"]


def test_a_help_case_gets_an_empty_manual_reply(client, auth):
    body = client.get("/inbox/email_501/reply?manual=true", headers=auth).json()
    draft = body["draft"]

    assert draft["kind"] == "manual_review"
    assert draft["body"] == ""
    assert draft["to"]
    assert draft["subject"].startswith("RE: ")


def test_the_same_help_case_keeps_its_template_in_document_check(client, auth):
    body = client.get("/inbox/email_501/reply", headers=auth).json()
    draft = body["draft"]

    assert draft["kind"] != "manual_review"
    assert draft["body"]


def test_nothing_is_drafted_for_a_non_comparison(client, auth):
    body = client.get("/inbox/email_002/reply", headers=auth).json()
    assert body["draft"] is None
    assert "why" in body


def test_a_reply_for_an_unknown_email_is_a_404(client, auth):
    assert client.get("/inbox/nope/reply", headers=auth).status_code == 404


def test_writing_into_gmail_without_a_mailbox_explains_itself(client, auth, monkeypatch, tmp_path):
    """A 400 naming the setup step, not a 500."""
    from vsmail.gmail import client as gmail_client

    monkeypatch.delenv(gmail_client.TOKEN_ENV, raising=False)
    monkeypatch.delenv(gmail_client.CREDENTIALS_ENV, raising=False)
    monkeypatch.setattr(gmail_client, "CREDENTIALS", tmp_path / "nope.json")
    monkeypatch.setattr(gmail_client, "TOKEN", tmp_path / "nope-token.json")

    response = client.post("/inbox/email_004/reply/gmail", headers=auth)
    assert response.status_code == 400
    assert "Connect Gmail" in response.json()["detail"]


def test_the_edited_words_are_what_the_gmail_draft_contains(
    client, auth, monkeypatch
):
    import base64

    from tests.gmail_fake import FakeGmail
    from vsmail.gmail import client as gmail_client

    gmail = FakeGmail()
    monkeypatch.setattr(gmail_client, "service", lambda: gmail)
    edited = {
        "to": "reviewer@example.com",
        "subject": "RE: corrected subject",
        "body": "These are the exact words the reviewer approved.",
    }

    response = client.post(
        "/inbox/email_004/reply/gmail", headers=auth, json=edited
    )

    assert response.status_code == 200
    assert response.json()["draft"]["body"] == edited["body"]
    raw = gmail.drafts_created[0]["message"]["raw"]
    message = base64.urlsafe_b64decode(raw.encode()).decode()
    assert edited["body"] in message
    assert f"To: {edited['to']}" in message


def test_a_mismatch_can_be_resolved_through_the_api(client, auth):
    """Regression, found by clicking Resolve on a mismatch.

    Cases are opened for what the run could not decide, so a MISMATCH — which
    was decided — had none, and every one of the 46 mismatch emails offered a
    Resolve card that returned 404.
    """
    before = client.get("/inbox/email_004", headers=auth).json()["result"]
    assert before["status"] == "MISMATCH"
    assert before["defect_fields"] == ["consignee", "notify_party"]

    for field in ("consignee", "notify_party"):
        r = client.post(
            "/review/email_004/resolve",
            headers=auth,
            json={"by": "test", "bl": {field: "EAST BRIGHT FZ-LLC"}},
        )
        assert r.status_code == 200, r.text
    client.post("/inbox/email_004/recheck", headers=auth)

    after = client.get("/inbox/email_004", headers=auth).json()["result"]
    assert after["status"] == "OK"


def test_the_drafted_reply_follows_the_corrected_verdict(client, auth):
    """Regression with teeth. The reply card keyed only on the email id, so
    after a correction it went on offering the draft asking the customer to
    amend fields that were now correct — one click from being sent."""
    asks_amendment = client.get("/inbox/email_004/reply", headers=auth).json()
    assert "Kindly amend" in asks_amendment["draft"]["body"]

    for field in ("consignee", "notify_party"):
        client.post(
            "/review/email_004/resolve",
            headers=auth,
            json={"by": "test", "bl": {field: "EAST BRIGHT FZ-LLC"}},
        )
    client.post("/inbox/email_004/recheck", headers=auth)

    confirms = client.get("/inbox/email_004/reply", headers=auth).json()
    assert confirms["draft"]["kind"] == "confirm"
    assert "please proceed to release" in confirms["draft"]["body"]


# -- the email being replied to ------------------------------------------
def test_the_incoming_email_comes_back_with_its_attachments(client, auth):
    """Approving a reply to an email you cannot read is a hollow approval."""
    body = client.get("/inbox/email_004/email", headers=auth).json()

    assert body["sender"] == "docs@vitalsolutions.sg"
    assert "email_004_SI.txt" in " ".join(body["attachments"])
    assert "email_004_BL.txt" in " ".join(body["attachments"])
    assert body["body"].strip()
    # What was read out of each slot, beside the filenames.
    assert "characters of text" in body["si_source"]
    assert {document["role"] for document in body["documents"]} == {"SI", "BL"}
    assert {document["name"] for document in body["documents"]} == {
        "email_004_SI.txt",
        "email_004_BL.txt",
    }


def test_a_pdf_document_is_served_inline_for_the_authenticated_viewer(client, auth):
    response = client.get("/inbox/email_059/documents/SI", headers=auth)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.content.startswith(b"%PDF")


def test_word_and_spreadsheet_documents_get_safe_text_previews(client, auth):
    word = client.get("/inbox/email_055/documents/BL/preview", headers=auth).json()
    sheet = client.get("/inbox/email_055/documents/SI/preview", headers=auth).json()

    assert word["mode"] == "text"
    assert sheet["mode"] == "text"
    assert word["text"].strip()
    assert sheet["text"].strip()


def test_document_viewer_rejects_unknown_roles_and_missing_documents(client, auth):
    assert client.get("/inbox/email_004/documents/OTHER", headers=auth).status_code == 404
    assert client.get("/inbox/email_506/documents/BL", headers=auth).status_code == 404


def test_document_bytes_stay_behind_authentication(client):
    assert client.get("/inbox/email_059/documents/SI").status_code == 401


def test_active_attachment_content_is_never_served_as_same_origin_html():
    from api.app_routes import _document_media_type

    assert _document_media_type("unsafe.html") == "application/octet-stream"
    assert _document_media_type("unsafe.svg") == "application/octet-stream"


def test_a_gmail_email_opens_directly_without_listing_the_mailbox(
    client, auth, monkeypatch, tmp_path, bundle
):
    from tests.gmail_fake import FakeGmail, as_message
    from vsmail.gmail import client as gmail_client
    from vsmail.gmail import source as gmail_source
    from vsmail.gmail.message import build_mime
    from vsmail.results import ResultStore

    record = bundle.get("email_004")
    message = build_mime(record, [], "judge@example.com")
    gmail = FakeGmail({"MSG-004": as_message(message, "MSG-004")})
    monkeypatch.setattr(gmail_client, "service", lambda: gmail)
    monkeypatch.setattr(gmail_source, "CACHE", tmp_path / "gmail-cache")

    store = ResultStore(tmp_path / "results.json")
    store.source = "gmail"
    store.results["email_004"].gmail_message_id = "MSG-004"
    store.save()

    response = client.get("/inbox/email_004/email", headers=auth)

    assert response.status_code == 200
    assert response.json()["subject"] == record.subject
    assert gmail.queries == [], "opening one card listed the whole mailbox"


def test_a_mailbox_failure_is_visible_instead_of_looking_like_a_missing_email(
    client, auth, monkeypatch
):
    from api import app_routes

    def broken(_email_id):
        raise RuntimeError("Gmail timed out")

    monkeypatch.setattr(app_routes, "_email_from_source", broken)
    response = client.get("/inbox/email_004/email", headers=auth)

    assert response.status_code == 502
    assert "Gmail timed out" in response.json()["detail"]


def test_the_trimmed_body_is_shorter_than_the_full_one(client, auth):
    """Both are returned: the trim is what the classifier saw, and a person
    needs the full text when they suspect it dropped something."""
    body = client.get("/inbox/email_004/email", headers=auth).json()

    assert len(body["core_body"]) < len(body["body"])
    assert body["core_body"] in body["body"]


def test_an_unknown_email_is_a_404_not_a_500(client, auth):
    assert client.get("/inbox/email_999/email", headers=auth).status_code == 404


# -- sending -------------------------------------------------------------
def test_sending_needs_a_recipient_subject_and_body(client, auth):
    response = client.post(
        "/inbox/email_004/reply/send", headers=auth, json={"to": "a@b.com"}
    )
    assert response.status_code == 422


def test_sending_without_a_mailbox_is_a_400_not_a_500(client, auth, monkeypatch):
    """No Gmail connected is a setup problem, and should read as one.

    The file paths are module-level constants in `vsmail.gmail.client`, read
    once at import, so they are patched there rather than through the
    environment — which would look like it worked and do nothing.
    """
    from pathlib import Path

    from vsmail.gmail import client as gmail_client

    monkeypatch.delenv("VS_GMAIL_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("VS_GMAIL_TOKEN_JSON", raising=False)
    monkeypatch.setattr(gmail_client, "CREDENTIALS", Path("no-such-file.json"))
    monkeypatch.setattr(gmail_client, "TOKEN", Path("no-such-token.json"))

    response = client.post(
        "/inbox/email_004/reply/send",
        headers=auth,
        json={"to": "a@b.com", "subject": "RE: x", "body": "hello"},
    )
    assert response.status_code == 400
