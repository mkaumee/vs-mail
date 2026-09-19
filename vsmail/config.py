"""Runtime configuration, read from the environment.

In the deployed setup these come from Railway's environment variables; the
API key never lives in this repository.
"""
import os

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

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
