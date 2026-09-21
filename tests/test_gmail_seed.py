"""Seeding a mailbox, and clearing it again."""
import base64

import pytest

from tests.gmail_fake import FakeGmail
from vsmail.gmail import seed as seeding
from vsmail.gmail.labels import SEED_LABEL
from vsmail.gmail.message import ID_HEADER, SEED_HEADER


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    """The real rate limit is 8/second; tests should not wait for it."""
    monkeypatch.setattr(seeding, "PER_SECOND", 10_000.0)


def _raw(body: dict) -> str:
    return base64.urlsafe_b64decode(body["raw"].encode()).decode("utf-8", "replace")


def test_seeding_inserts_one_message_per_email(bundle):
    gmail = FakeGmail()
    result = seeding.seed(gmail, bundle, limit=5)
    assert result["inserted"] == 5
    assert len(gmail.inserted) == 5
    assert result["failed"] == []


def test_each_message_carries_its_bundle_id(bundle):
    gmail = FakeGmail()
    seeding.seed(gmail, bundle, limit=3)
    for body in gmail.inserted:
        assert ID_HEADER in _raw(body)
        assert SEED_HEADER in _raw(body)


def test_the_original_sender_is_preserved(bundle):
    """The reason insertion is used at all — sending would overwrite this."""
    gmail = FakeGmail()
    seeding.seed(gmail, bundle, limit=1)
    assert bundle.emails()[0].sender in _raw(gmail.inserted[0])


def test_dates_come_from_the_header_not_the_insert_time(bundle):
    """Otherwise all 520 land in the same second and the mailbox is unreadable."""
    gmail = FakeGmail()
    seeding.seed(gmail, bundle, limit=2)
    for body in gmail.inserted:
        assert "Date:" in _raw(body)


def test_messages_are_labelled_so_a_reset_can_find_them(bundle):
    gmail = FakeGmail()
    seeding.seed(gmail, bundle, limit=2)
    seed_label_id = gmail.labels[SEED_LABEL]
    for body in gmail.inserted:
        assert seed_label_id in body["labelIds"]
        assert "INBOX" in body["labelIds"]


def test_attachments_are_carried(bundle):
    gmail = FakeGmail()
    # email_004 is the fourth record and carries an SI and a BL.
    seeding.seed(gmail, bundle, limit=4)
    with_attachments = [b for b in gmail.inserted if "email_004_SI.txt" in _raw(b)]
    assert with_attachments, "the SI should be attached by name"


def test_reset_bins_seeded_messages_rather_than_deleting_them(bundle):
    """messages.delete needs full-mailbox scope and cannot be undone."""
    gmail = FakeGmail({"M1": {"id": "M1"}, "M2": {"id": "M2"}})
    result = seeding.reset(gmail)
    assert result["trashed"] == 2
    assert set(gmail.deleted) == {"M1", "M2"}


def test_reset_only_looks_at_seeded_messages(bundle):
    gmail = FakeGmail({"M1": {"id": "M1"}})
    seeding.reset(gmail)
    assert any(SEED_LABEL in q for q in gmail.queries)


def test_progress_is_reported_as_it_goes(bundle):
    """Not just at the end.

    job.done used to be set once, after the whole minute of inserting had
    finished, so the page showed '0 of 520' throughout and then jumped —
    which reads as hung rather than working.
    """
    seen = []
    gmail = FakeGmail()
    seeding.seed(gmail, bundle, limit=5, on_progress=lambda done, total: seen.append((done, total)))

    assert seen == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


def test_seeding_without_a_callback_still_works(bundle):
    """Scripts pass none, and the route is the only caller that wants one."""
    assert seeding.seed(FakeGmail(), bundle, limit=2)["inserted"] == 2


def test_seeding_twice_skips_messages_already_in_the_mailbox(bundle):
    gmail = FakeGmail()
    first = seeding.seed(gmail, bundle, limit=3)
    second = seeding.seed(gmail, bundle, limit=3)

    assert first["inserted"] == 3
    assert second["inserted"] == 0
    assert second["skipped"] == 3
    assert len(gmail.inserted) == 3


def test_progress_reaches_total_even_when_an_email_is_skipped(bundle):
    gmail = FakeGmail()
    seeding.seed(gmail, bundle, limit=1)
    seen = []

    seeding.seed(
        gmail,
        bundle,
        limit=2,
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen == [(1, 2), (2, 2)]
