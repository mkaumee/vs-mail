"""Every attachment the bundle references must resolve to a Document."""
from vsmail.documents import read_document


def test_all_referenced_attachments_are_handled(bundle):
    readable = flagged = scans = 0

    for email in bundle.emails():
        for path in email.attachments:
            document = read_document(path, bundle.read_bytes(path))
            assert document.role in ("SI", "BL"), f"{path} has no slot"
            if not document.readable:
                flagged += 1
                assert document.error, "a flagged document must say why"
            else:
                readable += 1
                if document.images:
                    scans += 1
                assert not document.is_empty, f"{path} read as empty"

    # 126 emails carry attachments: 124 pairs plus two SI-only.
    assert readable + flagged == 250
    assert flagged == 2, "only the two corrupt BL PDFs should be flagged"
    assert scans == 6, "emails 512-514 ship six image-only pages"
