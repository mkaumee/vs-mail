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

## Signing in

Signing in and connecting a mailbox are different acts, and the app treats
them that way. Signing in says **who is using this**. Connecting Gmail says
**which mailbox it works on** — and that mailbox belongs to the deployment,
not to whoever is looking at the screen.

**Sign in with Google.** A second OAuth flow through the same client, asking
only for `openid email profile`, so the consent screen says "see your name and
email address" and nothing about mail. The result is a signed cookie: signed
rather than encrypted, because nothing in it is secret, but the email inside
is the identity every route believes and so it must not be editable. The
expiry is checked after the signature and separately — leaving that to the
cookie's `Max-Age` would trust the browser to enforce it.

**One more redirect URI**, on the same OAuth client, alongside the Gmail pair:

```
http://localhost:8000/auth/callback
https://<your-railway-domain>/auth/callback
```

Miss it and sign-in fails with `redirect_uri_mismatch`. `GET /auth/status`
reports the redirect it is about to use, which is otherwise invisible until
the browser is already at Google.

**Two ways in, both still valid.** A browser presents the session cookie.
Scripts, `RemoteProvider` and curl present `X-VS-Token` as they always have —
there is no browser to sign in with and nowhere to put a cookie. The sign-in
screen keeps the token folded underneath as a fallback, because being locked
out of your own app mid-demo is worse than an extra input.

| Variable | |
|---|---|
| `VS_AUTH_REDIRECT` | where Google returns the browser |
| `VS_SESSION_SECRET` | signs the cookie; falls back to `VS_SERVICE_TOKEN` |
| `VS_ALLOWED_USERS` | who may sign in — **empty means anyone** |

⚠️ **`VS_ALLOWED_USERS` is empty by default.** On a public URL that means
anybody with a Google account can sign in, read the inbox, start a DeepSeek
run on your credits, and press **Send** — and that mail leaves *your*
connected Gmail account. Setting it to your own address is one variable and
no code change.

**Signing out** clears the cookie and drops any stored token. Disconnecting
Gmail is separate, and is below.

## Reading a real Gmail mailbox

The pipeline reads the bundle's files by default. It can read a real mailbox
over the Gmail API instead.

### One-off setup, which cannot be automated

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com)
   and enable the Gmail API.
2. Under Credentials create an OAuth client ID of type **Web application** and
   add an authorised redirect URI for every place this app runs:

   ```
   http://localhost:8000/gmail/auth/callback
   https://<your-railway-domain>/gmail/auth/callback
   ```

   Download it as `credentials.json` in the repo root.
3. On the OAuth consent screen add the mailbox account as a **Test user** —
   the app is unverified, so only listed accounts may authorise it.

Use a throwaway Google account. Seeding puts 520 messages in a mailbox, and
that is not something to do to an inbox you care about. `credentials.json`
and `token.json` are both gitignored.

### Connecting

Start the app and press **Connect Gmail**. Consent opens in your own browser
and lands back on this service, which is what a web OAuth client means: there
is no terminal login step, and there is nothing for the scripts to prompt for.

A **Desktop app** client will not work, and the app says so by name if you
download one by mistake. A desktop client authorises by opening a browser on
the machine running the code and catching the redirect on a loopback port —
on a deployed server there is neither a browser nor a localhost to come back
to.

Set `VS_OAUTH_REDIRECT` wherever the app is not on `localhost:8000`. It is
configuration rather than something derived from the request, because behind
a proxy the request's own idea of its scheme and host is not reliable and
Google matches the registered URI exactly.

### Deployed, there are no files

`credentials.json` and `token.json` are both gitignored, so neither reaches
a deployment. Two variables stand in, and when either is set its file is not
consulted at all:

| Variable | Contents |
|---|---|
| `VS_GMAIL_CREDENTIALS_JSON` | the whole downloaded OAuth client |
| `VS_GMAIL_TOKEN_JSON` | the whole `token.json`, after connecting once |

The second is what keeps the mailbox connected across a redeploy — Railway's
filesystem does not survive one, so consent would otherwise be needed after
every push.

```bash
cat credentials.json  # → VS_GMAIL_CREDENTIALS_JSON
cat token.json        # → VS_GMAIL_TOKEN_JSON
```

### The seven-day token

**`gmail.modify` is a *restricted* scope.** An External consent screen left in
Testing issues refresh tokens that expire after **seven days**. Yours will stop
working about a week after you connect, and the failure is quiet — the mailbox
simply stops being readable.

**Publishing the consent screen is not the fix.** A restricted scope pulls in
Google's full verification *plus* a third-party CASA security assessment: weeks
of calendar time and real money. It is also what makes the console start
demanding a home page, a privacy policy and verified authorized domains —
fields that are optional while the app stays in Testing, and that a
`*.up.railway.app` domain cannot satisfy anyway, because Railway owns it and it
cannot be verified as yours. The Internal user type sidesteps all of it but
needs a Google Workspace organisation, which a `@gmail.com` account does not
have.

So treat it as the operating condition it is:

- **Stay in Testing.** Leave home page, privacy policy and authorized domains
  blank. Add the mailbox under **Test users**.
- **Re-connect weekly**, and on the morning of a demo whether or not it looks
  like it needs it.

The app reports this rather than failing silently: a refresh that comes back
`invalid_grant` shows as an expired authorisation with an invitation to press
Connect Gmail again, and `/gmail/status` carries `expired: true`.

### Disconnecting

**Disconnect** revokes the grant at Google rather than only deleting our copy.
Deleting alone leaves Google trusting it, so reconnecting skips the consent
screen entirely and anyone holding a copy of the token can still use it.

⚠️ When the token came from `VS_GMAIL_TOKEN_JSON`, **the app cannot remove
it** — a process cannot unset its deployment's environment variable. The
revoke still kills the token, so what is left is a dead value in a variable,
and the card says so by name instead of reporting a clean disconnect. Remove
the variable yourself.

### When it will not connect

`GET /gmail/status` answers this in one request:

| Field | Meaning |
|---|---|
| `credentials_source` | `environment`, `file`, or `null` — where the OAuth client was read from |
| `token_source` | the same, for the stored token |
| `credentials_present` | whether the client actually **parsed**, not just whether a variable is set |
| `expired` | the seven-day token has run out; re-connect |
| `error` | why, when something was found and could not be used |

`credentials_source: null` means nothing was set. `credentials_source:
"environment"` with `credentials_present: false` means something was set and
cannot be parsed — usually a paste that kept the `VS_GMAIL_CREDENTIALS_JSON=`
prefix, or one that was cut short. The error names which.

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

## The reply

What actually happens when a check finds something is an email. The bundle
says so itself — "kindly verify the BL matches the SI **before we release to
the line**", "revert with any discrepancy asap". The document under check is a
*draft*. Nobody here redrafts a bill of lading; they reply saying what is
wrong, and the carrier corrects its own draft.

So the app drafts that reply. It quotes both documents verbatim, asks for an
amendment, and waits for a person to approve it:

```
Dear Team,

Thank you for the draft bill of lading. Checking it against the shipping
instruction, the following do not agree:

  Consignee
    SI: "EAST BRIGHT FZ-LLC"
    Draft BL: "UAB NOVAKOPA"

Kindly amend the draft and resend for confirmation. The remaining fields match.
```

**Composed in code, not written by the model.** The sentences are identical
every time; only the values change, and those are exact strings from the
documents that carry legal weight. A model asked to write this email would be
retyping a consignee name — a transcription risk with no upside. The model
reads documents; the template writes prose.

**A clean check gets a reply too.** The draft is held until someone confirms
it, so silence is what stalls a shipment. The one exception is a clean check
that recorded doubt — where two readings disagreed, or the model disputed an
equivalence. Those are not offered for approval, because a confirmation that
suppresses the doubt would sound more certain to the customer than the run was
to itself.

**The words in the box are what goes out.** The draft is a starting point,
not a script — change anything, and *Reset to drafted* puts it back. An edit
is discarded if the verdict moves underneath it, because a hand-edited email
still asking a customer to amend a field that now agrees is worse than no
draft at all, and it is one click from being sent.

**The send never decides where it goes.** *Send* goes out through the Gmail
API, but only to the address in *Send test emails to*; the real recipient is
named in a banner at the top of the message and in an `X-VS-Would-Have-Gone-To`
header, so a diverted reply is still traceable. With no test address the
service refuses — a 422, not a silent send.

That refusal lives in `vsmail/gmail/send.py`, not in the page, because a page
can be a stale tab. `VS_TEST_RECIPIENT` pins a deployment safe when the page
sends nothing. Reaching a real address takes an explicit `allow_real` on the
request, and the bundle's senders — `docs@vitalsolutions.sg`,
`nirmala@fujitogrp.com` — look very much like real freight desks.

*Copy* and *Create Gmail draft* are still there, and the Gmail draft goes into
the original thread unsent.

## What the reply is checked against

A reply asserting a discrepancy is worth nothing if you cannot see the
discrepancy. Above every draft sits the email it answers — trimmed to the
request, with the full text a click away and the attachment names beside what
was actually read out of each — and then the seven-field table.

This matters more than it sounds. `email_004` reads as *agreeing* until you
look across the pair rather than down the column: both SI values say
`EAST BRIGHT FZ-LLC`, both BL values say `UAB NOVAKOPA`, and the address block
under both names is identical. Only the party changed. A checker shown just
the drafted reply has no way to tell a real defect from a false alarm.

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
