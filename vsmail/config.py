"""Runtime configuration, read from the environment.

In the deployed setup these come from Railway's environment variables; the
API key never lives in this repository.
"""
import os
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    """Read KEY=VALUE lines from a .env file into the environment.

    For local runs only. A variable already set in the real environment always
    wins, so a stray .env can never override what the deployment provides. A
    missing file is not an error — the deployed service has no .env at all.
    """
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Loaded before the settings below are read, so a local .env takes effect.
# Both the working directory and the repository root are checked.
load_env_file()
load_env_file(Path(__file__).resolve().parent.parent / ".env")

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

#: Below this, a classification is treated as the model saying it is unsure.
#: It never changes the submission — every email must carry one of the five
#: categories and the schema has no way to express doubt — but it marks the
#: case for human review.
CONFIDENCE_THRESHOLD = float(os.environ.get("VS_CONFIDENCE_THRESHOLD", "0.6"))

#: What a disagreement between two extraction passes does.
#: "advisory" keeps the verdict and flags the case; "blocking" escalates it.
#: Advisory is the default because escalating a correct MISMATCH loses a
#: caught defect, which is half the score.
CONSENSUS_MODE = os.environ.get("VS_CONSENSUS_MODE", "advisory")

#: The five categories every email is sorted into.
CATEGORIES = (
    "BL_COMPARISON",
    "SI_REQUEST",
    "INVOICE_QUERY",
    "GENERAL",
    "SPAM",
)

#: Outcomes for a comparison request.
STATUSES = ("OK", "MISMATCH", "NEEDS_REVIEW")

#: Why a comparison could not be decided.
REVIEW_REASONS = (
    "wrong_doc_type",
    "missing_attachment",
    "unreadable",
    "missing_value",
)

#: The seven fields compared between the SI and the draft BL, in report order.
FIELDS = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)
