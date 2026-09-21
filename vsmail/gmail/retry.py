"""Retry temporary Gmail failures without hiding permanent ones."""
from __future__ import annotations

import time

RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


class GmailTemporarilyBusy(RuntimeError):
    """Gmail's per-user quota did not recover within the retry window."""


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "resp", None), "status", None)


def _detail(exc: Exception) -> str:
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", "replace")
    return f"{content} {exc}".lower()


def _temporary(exc: Exception) -> bool:
    status = _status(exc)
    if status in (429, 500, 502, 503, 504):
        return True
    # Gmail reports per-user and project quota exhaustion as HTTP 403. Other
    # 403s (missing scopes, forbidden mailbox) are permanent and must surface.
    return status == 403 and any(
        marker in _detail(exc)
        for marker in (
            "ratelimitexceeded",
            "userratelimitexceeded",
            "quota exceeded",
            "quotaexceeded",
            "backenderror",
        )
    )


def execute(request, delays: tuple[float, ...] = RETRY_DELAYS):
    """Execute a Gmail request, backing off for quota and server failures.

    Six waits span just over a minute, long enough for Gmail's per-minute
    user quota to reset. Calls made by web jobs run in worker threads, so this
    does not freeze progress polling.
    """
    for attempt in range(len(delays) + 1):
        try:
            return request.execute()
        except Exception as exc:
            if not _temporary(exc):
                raise
            if attempt == len(delays):
                raise GmailTemporarilyBusy(
                    "Gmail temporarily reached its per-minute API limit. "
                    "Wait about a minute, then try again."
                ) from exc
            time.sleep(delays[attempt])
    raise RuntimeError("unreachable")  # pragma: no cover
