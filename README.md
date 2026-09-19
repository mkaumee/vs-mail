# VS-Mail

Email triage and shipping document verification over the SDOC hackathon bundle.

For each of the 520 emails the pipeline decides a category, and for document
comparison requests it checks a draft Bill of Lading against its Shipping
Instruction across seven fields — shipper, consignee, notify party, port of
loading, port of discharge, container count and gross weight — escalating for
human review when it cannot decide rather than guessing.

The design and the reasoning behind it are in [PLAN.md](PLAN.md).

## Running it

```bash
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

## A note on the score

`scripts/score_devset.py` and `POST /submit` report a **dev-set score, not the
real one**. There is no ground truth in the bundle, so both grade against 48
labels written by hand in `tests/devset.json`. The number measures agreement with
our own reading and is useful for catching regressions. Where a run disagrees with
a label, re-read the label before changing the pipeline.
