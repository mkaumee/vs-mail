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
from vsmail.gmail.message import attachment_uri, build_mime
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
    assert mailbox.queries[0] == "in:anywhere -in:trash"
    assert mailbox.include_spam_trash[0] is True


def test_every_email_comes_back_with_its_bundle_id(source):
    assert {e.email_id for e in source.emails()} == set(SAMPLE)


def test_a_limited_read_fetches_only_the_requested_messages(mailbox, tmp_path):
    limited = GmailSource(mailbox, cache=tmp_path / "limited")

    assert len(limited.emails(3)) == 3
    assert len(limited._message_ids) == 3


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


def test_a_small_inline_attachment_is_fetchable_without_attachment_api(tmp_path):
    import base64

    from vsmail.models import EmailRecord

    record = EmailRecord(
        "inline_1", "sender@example.test", "Documents", "Please compare.", ()
    )
    raw = b"SHIPPING INSTRUCTION\nShipper: Example"
    message = as_message(
        build_mime(record, [("Shipping Instructions.txt", raw)], "ops@example.test"),
        "INLINE1",
    )
    part = message["payload"]["parts"][1]
    part["body"].pop("attachmentId")
    part["body"]["data"] = base64.urlsafe_b64encode(raw).decode()
    gmail = FakeGmail({"INLINE1": message})
    inline_source = GmailSource(gmail, cache=tmp_path / "inline")

    email = inline_source.get_message("INLINE1")

    assert inline_source.read_bytes(email.attachment_for("SI")) == raw
    assert gmail.attachments == {}, "the full message already held the bytes"


def test_a_long_gmail_attachment_id_uses_a_fixed_size_cache_name(tmp_path):
    """Gmail ids can be longer than the filesystem's per-name limit."""
    gmail = FakeGmail()
    attachment_id = "ANGjdJ-" + "x" * 400
    gmail.attachments[("LONG1", attachment_id)] = b"document bytes"
    source = GmailSource(gmail, cache=tmp_path)

    data = source.read_bytes(
        attachment_uri("LONG1", attachment_id, "Shipping Instructions.pdf")
    )

    assert data == b"document bytes"
    cached = list((tmp_path / "attachments" / "LONG1").iterdir())
    assert len(cached) == 1
    assert len(cached[0].name) == 64


def test_an_existing_short_id_cache_still_loads(tmp_path):
    legacy = tmp_path / "attachments" / "M1" / "short-id"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"already cached")
    source = GmailSource(FakeGmail(), cache=tmp_path)

    assert source.read_bytes(
        attachment_uri("M1", "short-id", "Draft BL.pdf")
    ) == b"already cached"


def test_messages_are_cached_after_the_first_read(source, mailbox, tmp_path):
    source.emails()
    calls = len(mailbox.queries)
    GmailSource(mailbox, cache=tmp_path).emails()
    assert len(mailbox.queries) == calls + 1, "listing repeats; fetching should not"
    assert list((tmp_path / "messages").glob("*.json")), "messages should be on disk"


def test_a_known_gmail_id_loads_one_message_without_listing(mailbox, tmp_path):
    """Opening one card must not scan a judging mailbox with 520 messages."""
    direct = GmailSource(mailbox, cache=tmp_path)
    listings = len(mailbox.queries)
    record = direct.get_message("M0")

    assert record.email_id == "email_004"
    assert len(mailbox.queries) == listings


def test_message_ids_are_remembered_during_the_mailbox_read(source, mailbox):
    source.emails()
    listings = len(mailbox.queries)

    assert source.message_id_for("email_004") == "M0"
    assert len(mailbox.queries) == listings, "finding an id listed the mailbox twice"


def test_a_partial_cache_file_is_refetched_instead_of_breaking_the_card(
    mailbox, tmp_path
):
    cached = tmp_path / "messages" / "M0.json"
    cached.parent.mkdir(parents=True)
    cached.write_text('{"id":')

    record = GmailSource(mailbox, cache=tmp_path).get_message("M0")

    assert record.email_id == "email_004"
    assert json.loads(cached.read_text())["id"] == "M0"


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
