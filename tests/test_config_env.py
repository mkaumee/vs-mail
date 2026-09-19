"""Local .env loading.

Only for local runs. The deployed service has no .env; its variables come
from the platform environment, which must always win.
"""
import os

import pytest

from vsmail.config import load_env_file


@pytest.fixture(autouse=True)
def restore_environ():
    """load_env_file writes to os.environ directly, which monkeypatch cannot
    undo, so the whole environment is snapshotted and put back."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def test_values_are_read_from_a_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=abc123\nVS_PROVIDER=deepseek\n")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VS_PROVIDER", raising=False)

    load_env_file(env)
    assert os.environ["DEEPSEEK_API_KEY"] == "abc123"
    assert os.environ["VS_PROVIDER"] == "deepseek"


def test_the_real_environment_always_wins(tmp_path, monkeypatch):
    """A stray .env must never override what the platform provides."""
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=from-file\n")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-platform")

    load_env_file(env)
    assert os.environ["DEEPSEEK_API_KEY"] == "from-platform"


def test_quotes_and_comments_are_handled(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nVS_SERVICE_TOKEN="quoted-token"\n')
    monkeypatch.delenv("VS_SERVICE_TOKEN", raising=False)

    load_env_file(env)
    assert os.environ["VS_SERVICE_TOKEN"] == "quoted-token"


def test_a_missing_file_is_not_an_error(tmp_path):
    load_env_file(tmp_path / "nope.env")


def test_a_malformed_line_is_skipped(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("this line has no equals sign\nVS_PROVIDER=mock\n")
    monkeypatch.delenv("VS_PROVIDER", raising=False)

    load_env_file(env)
    assert os.environ["VS_PROVIDER"] == "mock"
