import pytest

from vsmail.inbox import Bundle


@pytest.fixture(scope="session")
def bundle() -> Bundle:
    return Bundle()


@pytest.fixture(scope="session")
def read_attachment(bundle):
    """Read a bundle attachment by path, as the pipeline would."""
    from vsmail.documents import read_document

    def _read(path: str):
        return read_document(path, bundle.read_bytes(path))

    return _read
