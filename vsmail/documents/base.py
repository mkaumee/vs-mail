"""Shared pieces for the attachment readers."""
from __future__ import annotations


class DocumentUnreadable(Exception):
    """An attachment could not be parsed at all.

    Readers raise this; `read_document` turns it into a flagged `Document`
    so a single corrupt file never halts a batch run. It maps onto the
    submission schema's `unreadable` review reason.
    """
