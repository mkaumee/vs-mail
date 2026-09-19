"""Email triage and shipping document verification for the SDOC bundle."""

import sys

if sys.version_info < (3, 10):  # noqa: E402
    raise RuntimeError(
        "VS-Mail needs Python 3.10 or newer (3.11+ recommended); this is "
        f"{sys.version_info.major}.{sys.version_info.minor}. The type "
        "annotations use `X | None`, which pydantic evaluates at import time "
        "and older versions cannot parse.\n"
        "On macOS the default `python3` is often 3.9. Create the virtualenv "
        "with a newer one, e.g.:\n"
        "    python3.12 -m venv .venv && source .venv/bin/activate\n"
        "    pip install -r requirements-dev.txt"
    )

__version__ = "0.1.0"
