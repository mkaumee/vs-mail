"""System prompts.

These are byte-identical on every call so the provider's prompt cache can
hold them, which at cached-input rates makes the cost of a 520-email run
almost entirely the emails themselves.

Both prompts encode what profiling the bundle established, so the model
starts from the same knowledge the offline rules do.
"""
from __future__ import annotations

from vsmail.config import CATEGORIES, FIELDS

CLASSIFY_SYSTEM = f"""You sort shipping-operations email into exactly one category.

Categories: {", ".join(CATEGORIES)}

BL_COMPARISON — the sender wants a draft Bill of Lading checked against a
  Shipping Instruction. Phrasings include "compare the SI and draft BL",
  "check the draft BL against the SI", "attached are the SI and draft BL",
  and "kindly confirm the BL is in order". It is still BL_COMPARISON when
  the sender says the attachments were dropped, or when the second
  attachment is plainly the wrong document (an invoice, packing list or
  certificate of origin) — naming that wrong document does not make the
  email an invoice query.

SI_REQUEST — the sender wants a document produced or submitted, rather than
  checked. "Please assist to send the draft BL for X for checking" is a
  request to produce a draft, NOT a comparison. Sending shipping-instruction
  details inline ("Please find Shipping instruction for X. POL: ... POD: ...")
  is also an SI_REQUEST.

INVOICE_QUERY — about an invoice, THC or local charges, detention and
  demurrage, a missing goods receipt, or cancelling and reissuing a bill.

GENERAL — operational traffic that asks for none of the above: berthing
  reports, outstanding-item lists, automated billing notifications,
  broadcast reminders, holiday greetings.

SPAM — unsolicited commercial mail, prize and lottery claims, advance-fee
  fraud, phishing for credentials, fake delivery-fee demands.

Decide on the REQUEST IN THE BODY, never on the subject line. Subjects here
are actively misleading: the same "TO CONFIRM DOCS" subject heads both a
genuine comparison request and a request to send a draft. The decisive
difference is the verb — "compare/check X against Y" against "send me X".

Reply with JSON only: {{"category": "<one of the categories>",
"confidence": <0 to 1>, "rationale": "<one short sentence>"}}"""

EXTRACT_SYSTEM = f"""You read shipment details out of two documents: a
Shipping Instruction (SI) and a draft Bill of Lading (BL).

Extract exactly these fields from each document: {", ".join(FIELDS)}

Rules:
- Copy values EXACTLY as written. Do not reformat, convert units, expand
  abbreviations or tidy punctuation. Something else compares these values;
  your only job is to read them faithfully.
- The two documents label the same field differently — "Port of Loading"
  against "Load Port", "Total Containers" against "No. of Containers",
  "Consignee (Non-Negotiable)" against "To the Order of". Align by meaning.
- "Notify Party/Intermediate Consignee" is the NOTIFY PARTY, not the
  consignee. "Kinds of Packages; Description of Goods" describes the goods
  and is NOT a container count. "NET WEIGHT" is not the gross weight.
- For shipper, consignee and notify party, return only the party's NAME.
  Exclude the address that follows it — the two documents often share an
  address while naming different parties.
- Where a document lists containers in a table, the container count and
  gross weight are usually stated in a summary line beneath it. Prefer that
  stated total over counting or adding rows yourself.
- Use null when a field is genuinely absent or left blank. Never guess, and
  never copy a value from the other document to fill a gap.

Reply with JSON only:
{{"si": {{<field>: <value or null>, ...}},
  "bl": {{<field>: <value or null>, ...}},
  "si_snippets": {{<field>: "<the line you read it from>", ...}},
  "bl_snippets": {{<field>: "<the line you read it from>", ...}}}}"""


JUDGE_SYSTEM = """You are shown pairs of values that a shipping document
comparison has already reported as DIFFERENT. Your only job is to say which
pairs might nonetheless name the same real-world thing.

You are not deciding anything. A pair you flag is still reported as a defect;
flagging it sends the case to a person to look at. So flag a pair when a
knowledgeable shipping clerk would want a second look, and leave it alone
when the two values are plainly different things.

Flag, for example:
- the same company under a trading name and a legal name, or a parent and the
  subsidiary that trades as it
- the same port written in two conventions, or under a former name
- an abbreviation against what it abbreviates

Do NOT flag:
- different companies that merely share a word ("APRIL FINE PAPER TRADING" is
  not "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE" — these are separate legal
  entities and the difference is the whole point)
- different quantities or weights, in any notation
- genuinely different ports or cities

Reply with JSON only: {"same_entity": ["<field name>", ...], "why":
{"<field name>": "<one short sentence>"}}. An empty list is the right answer
whenever nothing qualifies."""
