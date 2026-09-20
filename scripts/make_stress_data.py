#!/usr/bin/env python3
"""Build a second inbox of awkward cases.

The organizers' bundle is 520 real emails and it is left alone. What it does
not contain is the shapes that break a pipeline quietly: a weight written in
tonnes, an accented company name, a port code in a format nobody planned for,
an invoice number we hold no record of.

Each email here exists to answer one question, recorded in `expect` so a run
can be checked rather than eyeballed. Where the expectation is arguable it
says so — a few of these are here precisely because the right answer is not
obvious, and those are the interesting ones.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

OUT = Path("stress data")

#: (id, sender, subject, body, si_fields, bl_fields, expect, why)
#: si/bl None means no attachment.
FIELDS = ("SHIPPER", "CONSIGNEE", "NOTIFY PARTY", "PORT OF LOADING",
          "PORT OF DISCHARGE", "CONTAINERS", "GROSS WEIGHT")

BASE = {
    "SHIPPER": "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE",
    "CONSIGNEE": "KPP-ANTALIS (SINGAPORE) PTE. LTD.",
    "NOTIFY PARTY": "KPP-ANTALIS (SINGAPORE) PTE. LTD.",
    "PORT OF LOADING": "NHAVA SHEVA, INDIA",
    "PORT OF DISCHARGE": "SINGAPORE",
    "CONTAINERS": "6 x 40'HC",
    "GROSS WEIGHT": "22,000 KG",
}

COMPARE_BODY = (
    "Dear Team,\n\nPlease compare the SI and draft BL for {ref} and confirm.\n\n"
    "Best Regards,\nOps Desk"
)

CASES = [
    # -- weights ---------------------------------------------------------
    ("901", {"GROSS WEIGHT": "22 MT"}, {"GROSS WEIGHT": "22000 KGS"}, "OK",
     "tonnes against kilograms is the same weight"),
    ("902", {"GROSS WEIGHT": "1,234.50 KG"}, {"GROSS WEIGHT": "1234.5 KGS"}, "OK",
     "digit grouping and a trailing zero are formatting"),
    ("903", {"GROSS WEIGHT": "22MT"}, {"GROSS WEIGHT": "22,000 KG"}, "OK",
     "no space between number and unit"),
    ("904", {"GROSS WEIGHT": "22 MT"}, {"GROSS WEIGHT": "22 KG"}, "MISMATCH",
     "same number, different unit, is a real defect"),
    # -- ports -----------------------------------------------------------
    ("905", {"PORT OF DISCHARGE": "SINGAPORE"},
     {"PORT OF DISCHARGE": "SINGAPORE (SGSIN)"}, "OK",
     "a code on one side only"),
    ("906", {"PORT OF DISCHARGE": "SINGAPORE (SGSIN)"},
     {"PORT OF DISCHARGE": "JEBEL ALI, UAE (SGSIN)"}, "MISMATCH",
     "the email_119 trap: code carried over, port changed"),
    ("907", {"PORT OF DISCHARGE": "PORT KLANG (WESTPORT), MALAYSIA"},
     {"PORT OF DISCHARGE": "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)"}, "OK",
     "a parenthetical that is part of the name, plus a code"),
    ("908", {"PORT OF DISCHARGE": "SINGAPORE [SGSIN]"},
     {"PORT OF DISCHARGE": "SINGAPORE"}, "OK",
     "square brackets instead of parentheses — arguable, and worth knowing"),
    # -- names -----------------------------------------------------------
    ("909", {"CONSIGNEE": "KPP ANTALIS (SINGAPORE) PTE LTD"},
     {"CONSIGNEE": "KPP-ANTALIS (SINGAPORE) PTE. LTD."}, "OK",
     "hyphens and full stops are punctuation"),
    ("910", {"CONSIGNEE": "ACME PAPER LTD"},
     {"CONSIGNEE": "ACME PAPER (MIDDLE EAST) FZE"}, "MISMATCH",
     "different legal entities sharing a name"),
    ("911", {"CONSIGNEE": "CAFÉ DO BRASIL LTDA"},
     {"CONSIGNEE": "CAFE DO BRASIL LTDA"}, "OK",
     "an accent is not a different company"),
    ("912", {"CONSIGNEE": "  KPP-ANTALIS (SINGAPORE) PTE. LTD.  "},
     {"CONSIGNEE": "KPP-ANTALIS (SINGAPORE) PTE. LTD."}, "OK",
     "leading and trailing whitespace"),
    # -- containers ------------------------------------------------------
    ("913", {"CONTAINERS": "6 x 40'HC"}, {"CONTAINERS": "6"}, "OK",
     "the count is what is compared"),
    ("914", {"CONTAINERS": "6 x 40'HC"}, {"CONTAINERS": "6 x 20'GP"}, "OK",
     "ARGUABLE: same count, different equipment. We compare count only."),
    ("915", {"CONTAINERS": "10 x 20'FCL"}, {"CONTAINERS": "9 x 20'FCL"}, "MISMATCH",
     "one container short"),
    # -- other languages -------------------------------------------------
    ("919", {"CONSIGNEE": "CÔNG TY GIẤY ĐÀ NẴNG"},
     {"CONSIGNEE": "CONG TY GIAY DA NANG"}, "OK",
     "Vietnamese: Đ is a letter, not an accent, so NFKD alone misses it"),
    ("920", {"CONSIGNEE": "ØRSTED PAPER A/S"},
     {"CONSIGNEE": "ORSTED PAPER A/S"}, "OK",
     "Nordic stroke letters"),
    ("921", {"CONSIGNEE": "MÆRSK PAPER"}, {"CONSIGNEE": "MAERSK PAPER"}, "OK",
     "a ligature spelled out"),
    ("922", {"CONSIGNEE": "上海 紙業有限公司"},
     {"CONSIGNEE": "上海紙業有限公司"}, "OK",
     "CJK does not separate words with spaces"),
    ("923", {"CONSIGNEE": "上海紙業有限公司"},
     {"CONSIGNEE": "上海纸业有限公司"}, "MISMATCH",
     "ARGUABLE: traditional against simplified. Left as a difference for the "
     "equivalence judge to raise rather than folded by a table we might get "
     "subtly wrong."),
    ("924", {"CONSIGNEE": "ＡＣＭＥ ＰＡＰＥＲ ＬＴＤ"},
     {"CONSIGNEE": "ACME PAPER LTD"}, "OK",
     "full-width Latin"),

    # -- blanks and placeholders ----------------------------------------
    ("916", {"GROSS WEIGHT": "N/A"}, {"GROSS WEIGHT": "22,000 KG"}, "NEEDS_REVIEW",
     "a placeholder is a blank, not a value"),
    ("917", {"GROSS WEIGHT": "____ MT"}, {"GROSS WEIGHT": "22,000 KG"}, "NEEDS_REVIEW",
     "an underscore fill is a blank"),
    ("918", {"GROSS WEIGHT": "TBA"}, {"GROSS WEIGHT": "TBA"}, "NEEDS_REVIEW",
     "blank on both sides is still not a match"),
]

#: Emails that are not comparisons, to stress classification and answering.
OTHERS = [
    ("930", "ops@kargosmar.com",
     "Query on invoice 5299999999",
     "Hi,\n\nQuery on invoice 5299999999: is the THC included or billed "
     "separately? Please advise the breakdown.\n\nThanks",
     "INVOICE_QUERY", "an invoice we hold no record of — must not be invented"),
    ("931", "ops@kargosmar.com",
     "Staff parking",
     "Dear Team,\n\nWhat is the policy on staff parking permits for the new "
     "office?\n\nThanks",
     "GENERAL", "nothing in the corpus covers this"),
    ("932", "docs@vitalsolutions.sg",
     "TO CONFIRM DOCS _ 5RCY-68239",
     "Dear Team,\n\nPlease assist to send the draft BL for 5RCY-68239 for "
     "checking asap.\n\nThank you.",
     "SI_REQUEST", "the misleading subject: it says confirm, the body says send"),
    ("933", "billing@aprilasia.com",
     "Invoice 5250075931 and the draft BL",
     "Dear Team,\n\nTwo things: the GR is still missing for invoice "
     "5250075931, and please also compare the SI and draft BL for "
     "5AKR-61849.\n\nThanks",
     None, "ARGUABLE: asks two different things in one email"),
    ("934", "noreply@example.com", "", "", None, "no subject and no body at all"),
    ("935", "ops@kargosmar.com", "Re: (no content)",
     "?" * 3, None, "a body with no words in it"),
]


def render(values: dict) -> str:
    return "\n".join(f"{k}: {values[k]}" for k in FIELDS)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "inbox").mkdir(parents=True)
    (OUT / "attachments").mkdir()

    manifest = []

    for num, si_over, bl_over, expect, why in CASES:
        eid = f"email_{num}"
        ref = f"5STR-{num}00"
        si, bl = dict(BASE) | si_over, dict(BASE) | bl_over
        for role, values in (("SI", si), ("BL", bl)):
            (OUT / "attachments" / f"{eid}_{role}.txt").write_text(
                f"{'SHIPPING INSTRUCTION' if role == 'SI' else 'BILL OF LADING'}\n\n"
                + render(values) + "\n"
            )
        (OUT / "inbox" / f"{eid}.json").write_text(json.dumps({
            "email_id": eid,
            "from": "docs@vitalsolutions.sg",
            "subject": f"TO CONFIRM DOCS _ {ref}",
            "body": COMPARE_BODY.format(ref=ref),
            "attachments": [f"attachments/{eid}_SI.txt", f"attachments/{eid}_BL.txt"],
        }, indent=2))
        manifest.append({"email_id": eid, "expect": expect, "why": why})

    for num, sender, subject, body, expect, why in OTHERS:
        eid = f"email_{num}"
        (OUT / "inbox" / f"{eid}.json").write_text(json.dumps({
            "email_id": eid, "from": sender, "subject": subject,
            "body": body, "attachments": [],
        }, indent=2))
        manifest.append({"email_id": eid, "expect": expect, "why": why})

    # A commercial invoice in Chinese where the draft BL should be.
    eid = "email_942"
    (OUT / "attachments" / f"{eid}_SI.txt").write_text(render(BASE))
    (OUT / "attachments" / f"{eid}_BL.txt").write_text(
        "商业发票\nCOMMERCIAL INVOICE No. INV-99120\n\n"
        "卖方 Seller: APRIL FINE PAPER TRADING\n"
        "买方 Buyer: KPP-ANTALIS (SINGAPORE) PTE. LTD.\n"
        "金额 Amount: USD 48,200.00\n"
    )
    (OUT / "inbox" / f"{eid}.json").write_text(json.dumps({
        "email_id": eid, "from": "docs@vitalsolutions.sg",
        "subject": "TO CONFIRM DOCS _ 5STR-94200",
        "body": COMPARE_BODY.format(ref="5STR-94200"),
        "attachments": [f"attachments/{eid}_SI.txt", f"attachments/{eid}_BL.txt"],
    }, indent=2))
    manifest.append({"email_id": eid, "expect": "NEEDS_REVIEW",
                     "why": "a Chinese commercial invoice in the BL slot"})

    # A comparison whose BL never arrived, and one whose file will not open.
    eid = "email_940"
    (OUT / "attachments" / f"{eid}_SI.txt").write_text(render(BASE))
    (OUT / "inbox" / f"{eid}.json").write_text(json.dumps({
        "email_id": eid, "from": "docs@vitalsolutions.sg",
        "subject": "TO CONFIRM DOCS _ 5STR-94000",
        "body": COMPARE_BODY.format(ref="5STR-94000"),
        "attachments": [f"attachments/{eid}_SI.txt"],
    }, indent=2))
    manifest.append({"email_id": eid, "expect": "NEEDS_REVIEW",
                     "why": "the BL never arrived"})

    eid = "email_941"
    (OUT / "attachments" / f"{eid}_SI.txt").write_text(render(BASE))
    (OUT / "attachments" / f"{eid}_BL.pdf").write_bytes(b"%PDF-1.4 truncated and broken")
    (OUT / "inbox" / f"{eid}.json").write_text(json.dumps({
        "email_id": eid, "from": "docs@vitalsolutions.sg",
        "subject": "TO CONFIRM DOCS _ 5STR-94100",
        "body": COMPARE_BODY.format(ref="5STR-94100"),
        "attachments": [f"attachments/{eid}_SI.txt", f"attachments/{eid}_BL.pdf"],
    }, indent=2))
    manifest.append({"email_id": eid, "expect": "NEEDS_REVIEW",
                     "why": "a corrupt PDF"})

    (OUT / "expectations.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (OUT / "README.md").write_text(
        "# Stress inbox\n\n"
        "Awkward cases the organizers' bundle does not contain. Written for\n"
        "this project; `sample data/` is theirs and is never edited.\n\n"
        "Each email answers one question. `expectations.json` records the\n"
        "expected outcome and why, so `scripts/check_stress.py` can check a\n"
        "run rather than leaving it to be eyeballed.\n\n"
        "A few are marked ARGUABLE — they are here because the right answer\n"
        "is genuinely not obvious, and those are the ones worth arguing about.\n"
    )
    print(f"{len(manifest)} emails -> {OUT}")


if __name__ == "__main__":
    main()
