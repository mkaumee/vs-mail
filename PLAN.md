# VS-Mail — Build Plan

**Status:** v2 — scoring spine built; corrections from the build folded in
**Branch:** `agent-service`
**Context:** Hackathon. Shipping document verification (SI vs BL discrepancy detection).

---

## 1. The Strategic Bet

Every other team will build the same thing: a web page where you upload the provided
data file, and it prints a discrepancy report.

**We are not building a document diff tool. We are building an AI ops inbox.**

The SI/BL comparison is *one feature inside it*, not the product. That reframe alone
puts us in a different judging category.

Core differentiators:

1. **Live Gmail integration** — no uploading. The agent watches a real inbox.
2. **Every email gets handled**, not just comparison requests — classified, triaged,
   and given a drafted reply awaiting human approval.
3. **Drafted corrections** — on a mismatch, the system writes the correction email
   for the human to approve, rather than just reporting the problem.
4. **Priority lanes** — SI/BL document checks are the high-priority fast lane.
   Everything else (spam, general, invoice, new SI requests) queues below.

---

## 2. What the Hackathon Actually Requires (the rubric — do not lose this)

The baseline deliverable, which must be bulletproof before any extras:

- **Classify** emails into: document-comparison request, new SI request, invoice
  query, general message, spam.
- **Extract** shipment fields from SI and BL attachments (comparison requests only).
- **Compare** seven fields and surface mismatches side by side.
- **Escalate to a human** when it cannot complete the task — with context, not a guess
  and not a silent failure.

### The seven fields

| # | Field | Notes |
|---|-------|-------|
| 1 | Shipper | |
| 2 | Consignee | |
| 3 | Notify party | |
| 4 | Port of loading | aka "Load Port", "POL" |
| 5 | Port of discharge | aka "Discharge Port", "POD" |
| 6 | Container count | |
| 7 | Gross weight (kg) | unit normalization required |

### Required output — it is a machine-scored JSON file

⚠️ **This supersedes the prose-report reading of the brief.** The bundle ships a
`sample_submission.json` and a `loader.py`. The graded artifact is
`submission.json`: one entry per `email_id`, all 520 present.

```json
"email_004": {
  "category": "BL_COMPARISON",
  "status": "MISMATCH",
  "review_reason": null,
  "has_defect": true,
  "defect_fields": ["consignee", "notify_party"]
}
```

| Key | Allowed values |
|-----|----------------|
| `category` | `BL_COMPARISON` · `SI_REQUEST` · `INVOICE_QUERY` · `GENERAL` · `SPAM` |
| `status` | `OK` (all 7 match) · `MISMATCH` (≥1 differs) · `NEEDS_REVIEW` (cannot decide) |
| `review_reason` | `wrong_doc_type` · `missing_attachment` · `unreadable` · `missing_value` · `null` |
| `has_defect` | bool |
| `defect_fields` | list of the seven field names |

`sample_submission.json` is a pure template — every entry is `GENERAL`/`OK`. It
defines the schema, not the answers. **We do not have ground truth.**

### Scoring formula

```
final = 50% end-to-end (defects caught all the way through)
      + 30% Stage-1 macro-F1 (classification)
      + 20% Stage-3 defect-F1
NEEDS_REVIEW handling is reported as a separate reliability axis.
```

Two consequences that should drive our decisions:

1. **Macro-F1 weights rare categories equally.** `SPAM` (~16 emails) counts as much
   as `INVOICE_QUERY` (~198). Getting a small class badly wrong is far more
   expensive than the raw email count suggests.
2. **The UI and the Gmail integration earn zero points in this formula.** They are
   presentation and differentiation, not score. Build the scoring spine first.

### Self-scoring — ask the organizers for this

`loader.py` supports an HTTP source: `Inbox("http://host:8080")`, and
`inbox.submit(submission)` returns a scoreboard with `final_score`.

**The organizers are not providing that URL**, so we host the scorer ourselves —
see §5b. It grades against labels we wrote, so what it reports is a `devset_score`,
never a `final_score`. That distinction is load-bearing: a confident number computed
against our own guesses is worse than no number at all, because a number reads as
truth. What it genuinely buys us is regression detection.

---

## 2b. The Dataset — What Is Actually In The Bundle

520 emails in `sample data/inbox/*.json`. Each record is
`{email_id, from, subject, body, attachments[]}`.

### Attachment distribution

| | Count |
|---|---|
| Emails with **no** attachments | 394 |
| Emails with an SI + BL pair | 124 |
| Emails with **only** an SI (BL missing) | 2 — `email_507`, `email_509` |

| Format combo | Emails |
|---|---|
| `.txt` + `.txt` | 94 |
| `.pdf` + `.pdf` | 13 |
| `.docx` + `.xlsx` | 8 |
| `.xlsx` + `.xlsx` | 7 |
| `.pdf` + `.txt` | 2 |
| `.txt` only | 2 |

**`.xlsx` is 15 emails — the brief never mentioned Excel.** Don't get caught out.

### The planted edge cases (mostly clustered at email_501–520)

| Emails | Condition | Expected `review_reason` |
|---|---|---|
| 501, 502, 503, 504, 505 | BL slot holds a **Commercial Invoice / Packing List / Certificate of Origin** | `wrong_doc_type` |
| 506, 508, 510 | Body says "compare the SI and draft BL … *(attachments appear to have been dropped)*", zero attachments | `missing_attachment` |
| 507, 509 | SI present, BL absent | `missing_attachment` |
| 511, 515 | BL PDF is **corrupt** — PyMuPDF raises `FileDataError`, "no objects found" | `unreadable` |
| 512, 513, 514 | Both PDFs are **image-only scans** — zero text layer, one image per page | (must be read, not escalated) |
| 519, 520 | The **SI leaves a required field blank** — `SHIPPER:` and `CONSIGNEE:` with nothing after them | `missing_value` |

That accounts for all four review reasons. The last row was found while building
the parser, not from the brief.

### OCR: needed, but only barely

Of 28 PDFs, **20 have a clean text layer, 6 are image-only and 2 are corrupt**.
The six scans are just three emails (512, 513, 514). Everything else parses with
ordinary libraries.

So the vision path is required, but it is a **narrow fallback**, not the main road:
try text extraction first, fall back to rasterize-and-send-to-model only when the
text layer is empty. Three emails' worth of work, not the whole pipeline's.

### ⚠️ The hardest problem in this dataset: misleading subjects

**68 emails have a document-check-shaped subject but no attachments.** They are not
all `missing_attachment`. The subject line is actively useless — the same
`TO CONFIRM DOCS` subject appears on both of these:

| Email | Body (trimmed) | Truth |
|---|---|---|
| `email_506` | "Please **compare** the SI and draft BL for 070500263211 and confirm *(attachments appear to have been dropped)*" | genuine comparison request, attachment lost |
| `email_003` | "Please assist to **send** the draft BL for SIN832764835 for checking asap" | asking us to *produce* a document — not a comparison |

**The discriminator is the request verb in the body, not the subject.**
"compare/check X against Y" ≠ "send me X". ~91 emails use the "send me the draft BL"
phrasing. Misreading that cluster would wreck macro-F1 on two categories at once.

This also validates §4: hand-written regexes classified these badly in testing
(161 of 520 unmatched, including obvious comparison requests phrased as
"Pls assist to check the draft BL against the SI"). The phrasing variety is
exactly what an LLM is good at and regexes are bad at.

### Label variation is real — worked example, `email_004`

| SI label | BL label |
|---|---|
| `Consignee (Non-Negotiable):` | `To the Order of:` |
| `Notify:` | `Notify Party:` |
| `Total Containers:` | `Container Count:` |
| `Gross Wt (kgs):` | `Gross Weight (KG):` |

And a trap worth noting: in `email_004` the consignee **name** differs
(`EAST BRIGHT FZ-LLC` vs `UAB NOVAKOPA`) while the address block beneath it is
**identical in both documents**. Extract the party name, not the address blob, or
this defect disappears.

One more: `email_059_SI.pdf` and `email_208_SI.pdf` are titled
**"BILL OF LADING INSTRUCTION"**. Do not infer SI vs BL from the document heading —
use the attachment filename role (`_SI` / `_BL`).

---

### The advanced stage (where points are actually won)

- PDF and Word attachments — tables, varied page layouts.
- Scanned / image-only PDFs — OCR or a vision-capable LLM.
- Messy inputs — varied field labels, formatting differences, misleading subject
  lines, missing attachments.
- Reliability — unreadable document, missing value, or uncertain result must route
  to human review *with source evidence and a reason*. Failures visible. Retries
  allowed.

**Graded on two things that pull against each other:**
- **Accuracy** — catch real discrepancies AND raise no false alarms. A formatting
  difference ("MAERSK LINE" vs "Maersk Line") is *not* a discrepancy.
- **Knowing when to stop** — recognise an undependable decision and escalate.

---

## 3. The Model — DECIDED: DeepSeek V4.1 Flash

**Model ID: `deepseek-flash`** (aliases `deepseek-v4-flash` and
`deepseek-v4-flash-vision-exp` are still accepted, both served by V4.1-Flash).

| Property | Value |
|----------|-------|
| Vision | **Native multimodal** — own vision encoder, first Flash with it |
| Image formats | JPEG, PNG, GIF, WebP |
| Context | 1,048,576 in / 393,216 out |
| Price, off-peak | $0.15/M uncached in · $0.60/M out · **$0.003/M cached in** |
| Price, peak | $0.30/M in · $1.20/M out · $0.006/M cached |
| Also supports | Tool calling, prompt caching, extended reasoning |

⚠️ **Do not use `deepseek-chat` or `deepseek-reasoner`** — those legacy IDs were
discontinued 24 July 2026.

### Why this choice is good for us

1. **No separate OCR stage.** Native vision means the 6 image-only PDFs
   (emails 512-514) go straight to the model. See §2b — this is a narrow fallback
   for 3 emails, not the main road. Text extraction handles the other 22 PDFs.
2. **1M context = no chunking.** The entire SI and BL go into a single call
   together. Simpler *and* more accurate — the model sees both documents at once
   rather than us stitching separate extractions together.
3. **Cached input at $0.003/M makes redundancy nearly free.** Our extraction system
   prompt (field schema, label aliases, rules) is byte-identical on every email, so
   it caches. This makes **dual-extraction consensus** affordable: run extraction
   twice, auto-approve only when both runs agree, escalate to human review on
   disagreement. Real reliability story, negligible cost.

### Caveat

**PDF is not a directly accepted input format.** The 6 image-only PDFs must be
rasterized to PNG before the model will take them (`page.get_pixmap().tobytes("png")`).
Confirmed working — PyMuPDF, openpyxl and python-docx all parse this bundle cleanly.

### Still do this anyway

Put a thin provider interface in front of the LLM so it swaps with an env var.
One provider is a single point of failure, and an API outage during judging would
otherwise kill the demo.

---

## 4. Architecture Principle: The LLM Extracts, Code Decides

**Do not let the LLM decide equality.**

- LLM's job: **extract** the seven fields from each document into structured JSON.
- Our code's job: **normalize** and **compare**.

Reason: "MAERSK LINE" vs "Maersk Line" must be a non-event. An LLM asked
"do these match?" will sometimes flag it. The brief explicitly scores false alarms as
a failure mode — this is exactly where accuracy points get lost. Extraction is the
LLM's strength; judgment should be deterministic code we control and can test.

### ⚠️ Ports compare on the name, never on the UN/LOCODE

An earlier draft of this plan said to prefer the code when both documents carry
one. **That is wrong for this dataset.** `email_119` reads `PORT KLANG (WESTPORT),
MALAYSIA (MYPKG)` against `SINGAPORE, SINGAPORE (MYPKG)`: the code was carried over
unchanged while the port itself was altered, so comparing codes would hide a real
defect. Conversely `email_516` adds a code on one side only, which is not a defect.
Strip the code, compare the name.

The other normalization rules that matter, all confirmed against real pairs:
digit grouping and unit spelling are folded (`243588` ≡ `243,588`), metric tonnes
convert, the container count is the leading integer, and legal suffixes are **kept**
because `APRIL FINE PAPER TRADING` and `APRIL FINE PAPER TRADING (MIDDLE EAST) FZE`
are different entities.

---

## 5. Input Layer — Two Sources, One Pipeline

The bundle ships emails as JSON records (`inbox/email_*.json`) with attachments in
mixed formats (`.txt`, `.pdf`, `.xlsx`, `.docx` — see §2b). We build a Python
**seeder** that loads them into a real Gmail inbox via the Google API, so the system
processes the official hackathon data through a genuinely live integration.

⚠️ **Sequencing note:** the graded artifact is `submission.json`, which the Gmail
path earns no points for. The seeder is a differentiator, not a scorer. Build the
scoring spine first (§9).

### Use `users.messages.insert`, not `messages.send`

`insert` writes a message directly into the mailbox without it traveling through
SMTP. This matters for four concrete reasons:

1. **The spam samples.** Genuinely *sending* spam-shaped content gets it filtered
   into the Spam folder, or gets the sending account flagged. Our spam classifier
   would then never see the spam. `insert` sidesteps this entirely.
2. **Arbitrary `From:` headers.** Sample emails come from different senders. With
   `send`, everything arrives from our one account. With `insert`, each message
   keeps its real sender — which the classifier should be using as a signal.
3. **Arbitrary `Date:` headers.** We control the timeline instead of every message
   arriving within the same ten seconds.
4. **Clean resets.** Tag each seeded message with `X-VS-Seed: 1`, and a `--reset`
   flag can purge and re-seed. This is the demo reset button — worth its weight
   when the pipeline needs to run twice on stage.

**Scope required:** `gmail.insert`, or `gmail.modify` if we also want to write
labels back (we do — see feature ①).

### Keep `send` for exactly one thing

During the demo, sending one live email from a phone into the system inbox and
watching it get classified in real time is the most convincing moment available to
us. Bulk-seed with `insert`; keep `send` for the party trick.

### Two sources behind one interface

| Source | Behaviour | Purpose |
|--------|-----------|---------|
| `GmailSource` | Polls the real inbox | The live integration; the main demo |
| `FileSource` | Wraps the bundle's own `loader.Inbox` | No network; the fallback |

Identical downstream pipeline for both. If wifi dies mid-demo, flip a flag and
nobody can tell. `FileSource` is nearly free — the organizers' `loader.py` already
implements it, and it is also what the scoring run uses. This supersedes the earlier "Demo Mode" sketch in §6 — it's the
same idea, done as a source abstraction rather than a separate replay harness.

---

## 5b. The Service — Where The Key Lives

```
React frontend  ──►  FastAPI on Railway  ──►  DeepSeek API
                     (holds DEEPSEEK_API_KEY
                      and VS_SERVICE_TOKEN)
local pipeline  ──►  same service, via RemoteProvider
```

**The API key never enters this repository or a developer's machine.** It is set
in Railway's environment variables and exists only there. Three providers sit
behind one interface so nothing depends on a single path:

| Provider | Key | Use |
|---|---|---|
| `MockProvider` | none | tests, CI, offline runs, the baseline submission |
| `DeepSeekProvider` | from the environment | what runs *inside* the Railway service |
| `RemoteProvider` | none | local runs and the frontend, via the service |

**Auth fails closed.** Every route but `/health` needs `X-VS-Token`, compared in
constant time. With no token configured the guarded routes refuse to serve rather
than running open — an unauthenticated model endpoint on a public URL gets found
and drained, and the bill is real.

**Keep the direct path usable.** A Railway cold start or outage during judging must
not leave the pipeline with no way to run.

### The scorer we host ourselves

`POST /submit` grades a submission against our own dev-set labels and returns
`devset_score`. It deliberately has **no field named `final_score`**: this is not
the organizers' scorer and must never be mistaken for it. See §2.

---

## 6. Feature Backlog — Ranked by Impact per Hour

### ① Write the draft into Gmail, not just our app — *~2h, huge*
Don't just show the correction in our UI. Create a real Gmail draft in the actual
thread, properly threaded as a reply (`In-Reply-To` / `References` headers).

Demo moment: mismatch detected → switch to real Gmail → the reply is already sitting
there waiting. "It works inside the tools you already use" lands harder than any
dashboard.

Same with labels — push `VS/High-Priority`, `VS/Spam`, `VS/Invoice` back onto the real
messages. Two-way integration beats read-only every time.

### ② Click a mismatch → see it highlighted in both documents — *~4-6h, huge*
Every extracted field carries its provenance: page number and the source text snippet
it came from. Click "container count" → see the exact region in the SI and the BL,
side by side.

This directly answers the brief's hardest requirement (telling a real discrepancy
apart from a misread) and is the thing judges will remember visually.

### ③ Severity, not just mismatch — *~1h, high*
Not all seven fields are equal. Showing we know that proves domain understanding:

- **Critical** — consignee, notify party (legal title to cargo, customs clearance)
- **High** — gross weight (SOLAS VGM is a real regulation; wrong weight = vessel
  stability risk and a fine)
- **Medium** — container count, ports of loading/discharge

Sort the review queue by severity, not arrival time.

### ④ Show the normalization reasoning — *~2h, high*
When fields match but *look* different, display it:
- `"MAERSK LINE" ≡ "Maersk Line" — case normalized`
- `"22,000 KG" ≡ "22000 kgs" — unit normalized`

We're proving the absence of false alarms, which is otherwise invisible. Nobody claps
for a bug you didn't have unless you show them you didn't have it.

### ⑤ Learn from human corrections — *~2h, high*
When a reviewer fixes a bad extraction, store the label alias
(`"Load Port" → port_of_loading`) and use it next time. It's a JSON file and a lookup.
Sounds like machine learning, takes an afternoon.

### ⑥ Cases, not emails — *~3h, medium-high*
If a customer replies with a corrected BL, it links to the same case and re-runs,
showing what changed since the last run. Real ops work is a thread, not a message.

### ⑦ Impact counter on the dashboard — *~1h, medium*
"23 emails processed · 4 discrepancies caught · ~3.2 hours of manual checking saved."
Judges remember one number. Give them one.

### ⑧ Missing attachment handling — *~1h, medium*
"Please check the attached BL" with no attachment → auto-draft "could you resend the
attachment?" The brief explicitly lists this as a messy-input case, and it's ~20 lines.

---

## 7. Risks

### Don't lose the rubric while building the cool stuff
The graded artifact is `submission.json` and its schema (§2) — not a prose report,
and not the literal string "No mismatch detected" that the brief alone implied.
**Build that first, make it bulletproof, then pile features on top.** A gorgeous
inbox that fumbles the core comparison loses to a plain one that nails it.

### Live Gmail on stage is a coin flip
Wifi dies, OAuth tokens expire, APIs rate-limit at the worst moment.

Solved by the two-source abstraction in §5: `GmailSource` for the live path,
`FileSource` reading the same `.txt` samples off disk for the offline path, both
feeding an identical downstream pipeline. Show live Gmail if it works, flip a flag
if it doesn't, and nobody in the audience can tell.

### Gmail OAuth setup can block us
- Unverified app → test accounts must be added manually in the Google Cloud console.
  Fine for a demo, capped at 100 users.
- **Do this first.** It's boring, it can block everything, and it's the one task that
  doesn't get faster with more effort.
- **Skip Pub/Sub push notifications.** Poll every 10 seconds. Demos identically,
  saves ~2 hours.

### Single LLM provider
Covered in §3 — provider interface behind an env var.

---

## 8. Open Questions

1. ~~Which model?~~ **RESOLVED** — DeepSeek V4.1 Flash (`deepseek-flash`), see §3.
2. ~~What stack?~~ **RESOLVED** — Python + FastAPI for the agent, React for the
   frontend.
3. ~~Where is the sample data?~~ **RESOLVED** — in `sample data/`, profiled in §2b.
4. ~~Do the organizers have a scoring server?~~ **RESOLVED — no.** We host our
   own (§5b), scoring against hand labels and reporting `devset_score`.
5. **Is `score_cli.py` obtainable?** Even without ground truth, having the real
   scorer would tell us exactly how each axis is computed, and would let us check
   our formula against theirs. Still worth asking for.
6. **Are the dev-set labels right?** 48 emails, labelled by reading the source.
   The offline baseline agrees with all 48 — but the same person wrote both, so
   that agreement confirms the pipeline does what was intended, not that the
   labels are correct. A second pair of eyes on `tests/devset.json` is the
   highest-value review available.

---

## 9. Build Order

**Status: phases 1-4 are built.** 165 tests pass; the offline baseline runs all
520 emails in ~1.4s and produces a schema-valid submission in which every planted
edge case lands correctly. Phase 5 onward is the remaining work.

**Revised after reading the bundle.** The graded artifact is `submission.json` and
nothing else. Gmail and the UI score zero in the formula, so the scoring spine goes
first and the differentiators stack on top of a pipeline that already works.

### Phase 1 — the document layer (no LLM, fully testable)
Readers for `.txt` / `.pdf` / `.xlsx` / `.docx` behind one interface returning
`Document(text, images, readable, error)`. Must correctly report: corrupt file →
`unreadable`; empty text layer → hand back rasterized PNGs. Deterministic,
unit-testable, and it is the foundation everything else stands on.

### Phase 2 — classification
One LLM call per email over `from` + `subject` + `body` + attachment manifest.
Body-weighted, per §2b. Optimize for macro-F1, which means watching the small
classes (`SPAM`, `BL_COMPARISON`) not the big ones.

### Phase 3 — extraction and comparison
Extract the seven fields from SI and BL into structured JSON (both documents in one
call — the 1M window allows it). Normalize and compare **in code**, per §4.
Then the `NEEDS_REVIEW` decision tree: `wrong_doc_type`, `missing_attachment`,
`unreadable`, `missing_value`.

### Phase 4 — submission writer + dev-set eval
Emit all 520 entries. Hand-label a stratified sample (~40 emails, deliberately
including the 501-520 edge block) as a local dev set so we can measure instead of
guess. Replace with the real scoreboard the moment we get the server URL.

### Phase 5 onward — the differentiators
5. Gmail OAuth + seeder (§5)
6. UI: categorized inbox with priority lanes
7. Drafted replies → Gmail drafts + labels written back
8. Provenance / evidence highlighting
9. Severity, normalization display, impact counter
10. Learning aliases, cases
