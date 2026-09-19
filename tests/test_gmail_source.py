"""Reading a mailbox as if it were the bundle.

The strongest check here is the last one: the same emails, routed through
Gmail's message format and back, must reach exactly the same verdicts as
reading them off disk. Anything else means the round trip lost something.
"""
import asyncio
import json

import pytest

from tests.gmail_fake import FakeGmail, as_message
from vsmail import pipeline, submission as sub
from vsmail.gmail.labels import CATEGORY_LABELS, DEFECT_LABEL, REVIEW_LABEL, Labels, labels_for
from vsmail.gmail.message import build_mime
from vsmail.gmail.source import GmailSource
from vsmail.llm.mock import MockProvider

#: A slice with one of everything interesting: a real defect, a formatting
#: difference that must not be flagged, a wrong document, a corrupt file, a
#: scan, and three non-comparison categories.
SAMPLE = [
    "email_004", "email_055", "email_119", "email_501",
    "email_511", "email_512", "email_002", "email_003", "email_015",
]


@pytest.fixture(scope="module")
def mailbox(bundle):
    """A fake Gmail holding those emails, composed exactly as the seeder would."""
    gmail = FakeGmail()
    for index, email_id in enumerate(SAMPLE):
        record = bundle.get(email_id)
        files = [(p.split("/")[-1], bundle.read_bytes(p)) for p in record.attachments]
        message_id = f"M{index}"
        composed = build_mime(record, files, to="ops@example.test")
        gmail.store[message_id] = as_message(composed, message_id)
        for slot, (name, data) in enumerate(files):
            gmail.attachments[(message_id, f"att{slot + 1}")] = data
    return gmail


@pytest.fixture
def source(mailbox, tmp_path):
    return GmailSource(mailbox, cache=tmp_path)


def test_the_whole_mailbox_is_read_including_spam(source, mailbox):
    """A misfiled email is still an email the desk has to deal with."""
    source.emails()
    assert mailbox.queries[0] == "in:anywhere"


def test_every_email_comes_back_with_its_bundle_id(source):
    assert {e.email_id for e in source.emails()} == set(SAMPLE)


def test_attachments_are_fetchable_and_correct(source, bundle):
    record = source.get("email_004")
    from_gmail = source.read_bytes(record.attachment_for("SI"))
    from_disk = bundle.read_bytes(bundle.get("email_004").attachment_for("SI"))
    assert from_gmail == from_disk


def test_a_binary_attachment_survives_the_round_trip(source, bundle):
    """email_512's documents are scanned PDFs; base64 has to be lossless."""
    record = source.get("email_512")
    assert source.read_bytes(record.attachment_for("SI")) == bundle.read_bytes(
        bundle.get("email_512").attachment_for("SI")
    )


def test_messages_are_cached_after_the_first_read(source, mailbox, tmp_path):
    source.emails()
    calls = len(mailbox.queries)
    GmailSource(mailbox, cache=tmp_path).emails()
    assert len(mailbox.queries) == calls + 1, "listing repeats; fetching should not"
    assert list((tmp_path / "messages").glob("*.json")), "messages should be on disk"


def test_an_unknown_email_id_raises(source):
    with pytest.raises(KeyError):
        source.get("email_999")


def test_gmail_and_disk_reach_identical_verdicts(source, bundle):
    """The check that matters: same emails, same answers, different source."""
    from_gmail = asyncio.run(pipeline.run(source, MockProvider()))
    wanted = [e for e in bundle.emails() if e.email_id in set(SAMPLE)]
    from_disk = asyncio.run(pipeline.run(bundle, MockProvider(), emails=wanted))

    assert sub.build(from_gmail) == sub.build(from_disk)


def test_labels_follow_the_verdict():
    assert labels_for({"category": "SPAM", "status": "OK"}) == [CATEGORY_LABELS["SPAM"]]
    assert REVIEW_LABEL in labels_for(
        {"category": "BL_COMPARISON", "status": "NEEDS_REVIEW"}
    )
    assert DEFECT_LABEL in labels_for(
        {"category": "BL_COMPARISON", "status": "MISMATCH"}
    )


def test_labels_are_created_once_and_reused(mailbox):
    labels = Labels(mailbox)
    first = labels.id_for("VS/Spam")
    assert labels.id_for("VS/Spam") == first
    assert list(mailbox.labels) == ["VS/Spam"], "a second call must not create another"


def test_applying_a_label_modifies_the_right_message(mailbox):
    Labels(mailbox).apply("M0", ["VS/Spam", REVIEW_LABEL])
    message_id, applied = mailbox.label_calls[-1]
    assert message_id == "M0"
    assert len(applied) == 2
