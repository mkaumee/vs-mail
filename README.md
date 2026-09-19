# VS-Mail

Email triage and shipping document verification over the SDOC hackathon bundle.

For each of the 520 emails the pipeline decides a category, and for document
comparison requests it checks a draft Bill of Lading against its Shipping
Instruction across seven fields — shipper, consignee, notify party, port of
loading, port of discharge, container count and gross weight — escalating for
human review when it cannot decide rather than guessing.

The design and the reasoning behind it are in [PLAN.md](PLAN.md).

## Running it

**Python 3.10 or newer is required** (3.11+ recommended). On macOS the default
`python3` is often 3.9, which cannot parse the `X | None` annotations pydantic
evaluates at import time — create the virtualenv with a newer interpreter:

```bash
python3.12 -m venv .venv && source .venv/bin/activate

pip install -r requirements-dev.txt

# Offline: no API key, no network. Produces a full baseline submission.
python scripts/run_submission.py --provider mock

# Score it against the hand-written dev set.
python scripts/score_devset.py

pytest -q
```

`submission.json` lands in the working directory with one entry per email.

### Running against the model locally

Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY`. It is read on import,
and a variable already set in your shell always wins over the file. `.env` is
gitignored.

```bash
cp .env.example .env          # then fill in DEEPSEEK_API_KEY

# Smoke-test on a handful of emails before spending a full pass.
python scripts/run_submission.py --provider deepseek \
  --only email_004 email_055 email_119 email_512 --out probe.json

# The full run, kept separate so it can be diffed against the baseline.
python scripts/run_submission.py --provider deepseek --out submission.deepseek.json
python scripts/score_devset.py submission.deepseek.json
```

| Flag | |
|---|---|
| `--only ID [ID ...]` | process just these emails |
| `--limit N` | process the first N |
| `--concurrency N` | in-flight emails, default 12; lower it if you hit rate limits |

A subset run is labelled as such and is **not** a submittable file — it does not
cover all 520 emails.

## The web app

Everything below can be driven from a browser: process the inbox, seed and
clear Gmail, watch for new mail, and work the review queue. No terminal
during a demo.

```bash
cd frontend && npm install && npm run build && cd ..
export VS_SERVICE_TOKEN=pick-something
uvicorn api.main:app
```

Open <http://localhost:8000>. The page asks for that token once and keeps it
in the browser, so the built app carries no credential of its own.

The build lands in `api/static`, which the same FastAPI app serves — one URL,
one deploy, no CORS. For frontend work with hot reload, `npm run dev` in
`frontend/` proxies the API.

The inbox is laid out as lanes rather than one long list sorted by arrival,
because the lane that matters is the one holding documents to check.
Selecting an email shows all seven fields side by side, with the differing
ones marked — and, where two values are written differently but mean the
same thing, a note saying why it was accepted. Proving the absence of a false
alarm is otherwise invisible.

## The service

```bash
uvicorn api.main:app --reload
```

| Route | |
|---|---|
| `GET /health` | open, so a deployment can be checked without the secret |
| `POST /classify` | one email to a category |
| `POST /extract` | SI and BL to raw field values |
| `POST /compare` | verdict plus the per-field detail |
| `POST /run` | the whole bundle to a submission |
| `POST /submit` | grade a submission against the dev set |

Everything except `/health` needs an `X-VS-Token` header.

## Deploying to Railway

Set these as Railway environment variables. **The API key belongs here and
nowhere else** — not in this repository, not in a `.env` on your machine.

| Variable | |
|---|---|
| `DEEPSEEK_API_KEY` | your key |
| `VS_SERVICE_TOKEN` | any long random string; callers must send it |
| `VS_PROVIDER` | `deepseek` |

`railway.json` sets the start command and points the healthcheck at `/health`.
With no `VS_SERVICE_TOKEN` configured the guarded routes return 503 rather than
serving an unauthenticated model endpoint to the internet.

To drive the deployed service from a local run:

```bash
export VS_SERVICE_URL=https://<your-app>.up.railway.app
export VS_SERVICE_TOKEN=<the same token>
python scripts/run_submission.py --provider remote
```

## Reading a real Gmail mailbox

The pipeline reads the bundle's files by default. It can read a real mailbox
over the Gmail API instead.

### One-off setup, which cannot be automated

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com)
   and enable the Gmail API.
2. Under Credentials create an OAuth client ID of type **Desktop app**;
   download it as `credentials.json` in the repo root.
3. On the OAuth consent screen add the mailbox account as a **Test user** —
   the app is unverified, so only listed accounts may authorise it.

Use a throwaway Google account. Seeding puts 520 messages in a mailbox, and
that is not something to do to an inbox you care about. `credentials.json`
and `token.json` are both gitignored.

### Seeding, reading, labelling

```bash
python scripts/seed_gmail.py                 # insert the 520
python scripts/run_submission.py --source gmail --provider mock --out gmail.json
python scripts/diff_submissions.py submission.mock.json gmail.json
python scripts/run_submission.py --source gmail --labels
python scripts/seed_gmail.py --reset         # bin them again
```

**That diff should be empty**: the same emails reach the same verdicts
whether they come from files or from Gmail.

The dataset is loaded with `users.messages.insert` rather than being sent,
and the reason is fidelity. The bundle's emails come from dozens of senders;
real delivery cannot preserve those, because SPF and DKIM exist to stop
forged senders, so sent mail arrives from whichever account sent it and the
classifier loses a signal on all 520.

`--labels` writes the triage back as `VS/BL-Comparison`, `VS/Spam`,
`VS/Needs-Review`, `VS/Defect-Found` and so on, so the decisions show up in
Gmail itself rather than only in our own output.

### Watching for live mail

```bash
python scripts/watch_gmail.py
python scripts/send_test_email.py            # in another terminal
```

The watcher polls every ten seconds and processes whatever is new. Unlike
the seeded dataset, a sent message really travels and arrives on its own —
email the account from a phone and it will be picked up the same way.

**The whole mailbox is read, Spam included** (`in:anywhere`). If Gmail's own
filter misfiles something, that is exactly the email an ops desk still has to
deal with, and a system whose job includes recognising spam should be looking
where spam actually lands.

## Human review

The pipeline escalates what it cannot settle. This is where a person settles it.

```bash
python scripts/run_submission.py --provider mock      # opens cases
python scripts/review.py list                         # the queue, worst first
python scripts/review.py show email_516               # the evidence
python scripts/review.py resolve email_516 \
  --by ops.mitchelle --supply "si.gross_weight_kg=235,550 KG"
python scripts/run_submission.py --provider mock      # the verdict changes
```

**A resolution never edits a verdict.** The reviewer supplies or corrects an
*input* and the comparator runs again over it, so a corrected email reaches
its outcome by exactly the path an uncorrected one does. Supply a wrong value
and you get a `MISMATCH`, not a rubber stamp. `--settle-status` can force an
outcome without values, and is recorded separately because it is the one
action that bypasses the comparator.

Corrections persist in `review.json` (gitignored) and are re-applied on later
runs — without that, the pipeline's statelessness would lose every decision on
the next run.

The queue is ordered by what a wrong value costs: consignee and notify party
are critical because they carry legal title to the cargo and drive customs
clearance, gross weight is high because it is a SOLAS VGM declaration, and a
document that is missing, unreadable or simply the wrong document outranks any
single field because it blocks the whole comparison.

The same thing over HTTP: `GET /review`, `GET /review/{id}`,
`POST /review/{id}/resolve`, `POST /review/{id}/retry` — the last reprocesses
one email without redoing the other 519.

## A note on the score

`scripts/score_devset.py` and `POST /submit` report a **dev-set score, not the
real one**. There is no ground truth in the bundle, so both grade against 51
labels written by hand in `tests/devset.json`. The number measures agreement with
our own reading and is useful for catching regressions. Where a run disagrees with
a label, re-read the label before changing the pipeline.

The offline provider scores 1.000 on the weighted axes but only 0.824 on review
reasons, because it cannot read the three scanned emails and escalates them
instead of comparing them. That gap is the measurable difference a vision-capable
provider makes.

### When the model is unsure

Two signals, both surfaced by `--explain` and neither able to change the
submission on its own:

| Signal | |
|---|---|
| Low classification confidence | Below `VS_CONFIDENCE_THRESHOLD` (0.6) the case is flagged. The model's best guess still ships — every email needs one of the five categories and the schema cannot express doubt — so macro-F1 is untouched. |
| Two readings that differ | Extraction runs twice, the second pass with the documents in reversed order. A field read differently depending on order is unstable and gets flagged. |

The second pass swaps the document order rather than repeating the call
because the client sends `temperature: 0` — an identical repeat returns
identical JSON, agrees with itself and catches nothing.

`VS_CONSENSUS_MODE` decides what a disagreement does. `advisory`, the default,
keeps the verdict and flags the case. `blocking` escalates it, which costs a
caught defect whenever the verdict was right, so it is opt-in and should be
measured with `scripts/diff_submissions.py` before being turned on.

A deterministic provider has no second pass and reports no uncertainty. That
is accurate rather than a gap: repeating a deterministic reading tells you
nothing.

### Auditing a verdict

```bash
python scripts/run_submission.py --provider deepseek --only email_512 --explain
python scripts/export_pages.py email_512
```

The first prints the values read from each document; the second writes the
scanned pages out as PNGs. For an image-only document there is no second opinion
to check against, so putting the two side by side is the only way to tell a
correct reading from a confident-looking invention.
