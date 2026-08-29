# Personal IPO Research Agent

A small, readable Python project that runs every day at **6:00 PM IST** in GitHub Actions, finds **mainboard IPOs opening on the next NSE market day**, builds a source-backed evidence package, makes **one OpenRouter LLM call per IPO**, generates a PDF, and emails the reports.

The project intentionally uses very little infrastructure: **GitHub Actions + Python + OpenRouter + Gmail SMTP**. AWS is not required.

## What V1 does

1. Determine the next market day using weekends + NSE's current-year trading holiday data.
2. Discover mainboard IPOs using a configurable provider.
3. Keep only IPOs whose opening date equals the next market day.
4. Verify/enrich the issue against NSE public IPO data where available.
5. Locate and download the RHP/DRHP from provider/official candidates.
6. Extract only decision-relevant RHP sections.
7. Best-effort extract structured financial rows and calculate deterministic ratios in Python.
8. Collect recent news through Google News RSS, deduplicate it, and rank meaningful events deterministically.
9. Send one structured evidence package to OpenRouter.
10. Validate the model's JSON response with a strict Pydantic schema.
11. Apply deterministic sanity rules to the verdict.
12. Render a consistent PDF from a Jinja HTML template.
13. Send one daily email to `EMAIL_TO`, with all successful PDFs attached and any IPO failures listed in the body.
14. Send technical failure notifications separately to `FAILURE_TO`.
15. Keep `processed_ipos.json` short by deleting records older than 15 days.
16. Upload PDFs as GitHub Actions artifacts for 15 days.

## Architecture

```text
GitHub Actions - 18:00 IST
        |
        v
NSE market calendar
        |
        v
Next market day
        |
        v
IPO provider
        |
        +-- no matching IPO -> silent exit
        |
        v
For each IPO independently
        |
        +--> NSE verification/enrichment
        +--> RHP/DRHP collector
        +--> relevant-section extraction
        +--> deterministic financial calculations
        +--> recent-news collection + event scoring
        |
        v
Evidence validation
        |
        v
ONE OpenRouter call
        |
        v
Strict JSON validation
        |
        v
Deterministic sanity checks
        |
        v
Jinja HTML -> WeasyPrint PDF
        |
        v
One Gmail SMTP email + N PDF attachments
```

## IPO providers

Set `IPO_PROVIDER` to one of:

- `auto` - use IPO Guru when `IPO_GURU_API_KEY` exists, otherwise use NSE.
- `ipo_guru` - documented free API; useful for GMP and subscription data.
- `upstox` - documented IPO API; requires an Upstox access token.
- `nse` - no-key NSE public website endpoint. This endpoint is public-facing but undocumented and may occasionally block cloud runner IPs.

For a personal GitHub Actions project, **`auto` is the recommended setting**. If NSE blocks GitHub-hosted runners, obtain the free IPO Guru key and `auto` will use it for discovery while still attempting NSE verification.

## Meaningful news-event prioritization

The LLM does not receive every IPO article it can find. Python first scores and filters events.

High-priority event types include:

- SEBI/regulatory action, fraud/probe, auditor issues, default/insolvency
- CEO/CFO/MD/director changes
- major customer loss or contract cancellation/win
- plant shutdown/fire/accident or major capacity commissioning
- debt/rating changes
- acquisition, merger, JV, major expansion or approval

Scoring combines:

- materiality of the event type
- recency
- source quality
- a penalty for generic IPO/GMP/listicle coverage

Near-duplicate headlines are merged, and no event type can dominate the final list. By default, at most 10 events reach the LLM.

## Determinism and correctness controls

The model is deliberately not asked to do everything.

### Python owns

- market-day calculation
- dates and normalization
- issue-size/price/lot parsing
- financial calculations when extraction is reliable
- event scoring and deduplication
- evidence hashes
- processed state
- PDF layout
- email delivery

### The LLM owns

- business understanding
- interpretation of financial quality
- OFS/promoter context
- materiality of risks
- valuation reasoning from supplied evidence
- fundamentals vs market narrative
- `APPLY / DEEP ANALYSE / IGNORE`

The OpenRouter call uses strict structured output when the configured model supports it. The response is validated locally again with Pydantic.

Important sanity rules include:

- `LOW` confidence cannot automatically return `APPLY`.
- `APPLY` is rejected when core financial evidence is still a material data gap.
- valuation cannot be called reasonable when the IPO price is unavailable.
- evidence IDs returned by the model must exist in the supplied evidence package.

## Failure behavior

The workflow distinguishes these states:

```text
NO IPO               -> no email
DISCOVERY FAILURE    -> FAILURE_TO
ONE IPO FAILS        -> other IPOs continue
PARTIAL FAILURE      -> EMAIL_TO gets good reports + failed IPO names
                         FAILURE_TO gets technical failure details
ALL IPOs FAIL        -> EMAIL_TO gets the failure summary
                         FAILURE_TO gets technical failure details
EMAIL FAILURE        -> attempt FAILURE_TO; workflow fails
```

A failure for one IPO never blocks processing of the remaining IPOs.

## Project layout

```text
.github/workflows/daily-ipo.yml
src/
  main.py
  config.py
  models.py
  market_calendar.py
  exchange_verifier.py
  evidence.py
  calculations.py
  validation.py
  llm.py
  pdf_report.py
  mailer.py
  state.py
  providers/
    base.py
    factory.py
    ipo_guru.py
    upstox.py
    nse.py
  collectors/
    prospectus.py
    financials.py
    news.py
prompts/ipo_analyst.md
templates/report.html
data/processed_ipos.json
tests/
```

## GitHub configuration

### Secrets

Create these under **Settings -> Secrets and variables -> Actions -> Secrets**:

```text
OPENROUTER_API_KEY
EMAIL_FROM
EMAIL_APP_PASSWORD
EMAIL_TO
FAILURE_TO
```

Optional provider secrets:

```text
IPO_GURU_API_KEY
UPSTOX_ACCESS_TOKEN
```

`EMAIL_TO` and `FAILURE_TO` support one or multiple comma-separated recipients:

```text
EMAIL_TO=user1@gmail.com,user2@gmail.com
FAILURE_TO=owner1@gmail.com,owner2@gmail.com
```

### Variables

Recommended variables:

```text
IPO_PROVIDER=auto
OPENROUTER_MODEL=openrouter/free
OPENROUTER_TEMPERATURE=0.1
OPENROUTER_MAX_TOKENS=8000
NEWS_LOOKBACK_DAYS=730
NEWS_MAX_EVENTS=10
```

The model is configuration, not code. You can switch OpenRouter models without modifying Python.

## Gmail setup

Use a Gmail App Password rather than your normal account password.

1. Enable two-step verification on the sending Google account.
2. Create an App Password.
3. Store it as `EMAIL_APP_PASSWORD`.
4. Store that Gmail address as `EMAIL_FROM`.

The project uses `smtp.gmail.com:465` with SMTP over SSL.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Export the variables from `.env` in your preferred way, then run:

```bash
pytest -q
python -m src.main --dry-run
```

For deterministic date testing:

```bash
python -m src.main --today 2026-08-28 --dry-run
```

## GitHub schedule

The workflow uses:

```yaml
- cron: "30 12 * * *"
```

GitHub cron is UTC, so 12:30 UTC is 18:00 IST.

The workflow also supports manual `workflow_dispatch` runs with a dry-run checkbox.

## `processed_ipos.json`

Only short-lived execution state is committed:

```json
{
  "processed": {
    "example-limited_2026-09-01": {
      "status": "EMAIL_SENT",
      "updated_at": "2026-08-31T12:45:00+00:00",
      "verdict": "DEEP ANALYSE",
      "confidence": "HIGH",
      "evidence_hash": "...",
      "report_file": "2026-09-01_example-limited.pdf"
    }
  }
}
```

Records older than 15 days are removed at the start of each run. A record is skipped only when its status is `EMAIL_SENT`; a previously failed IPO can be retried on a rerun.

## RHP handling

The system never sends a full 300-500 page prospectus to the model.

It attempts to extract only sections such as:

- Risk Factors
- Objects of the Issue
- Industry Overview
- Our Business
- Financial Information
- Capital Structure
- Basis for Offer Price
- Management
- Promoters
- Litigation
- Related Party Transactions
- Outstanding Indebtedness

If section extraction is ambiguous, it uses conservative keyword windows. If core Business, Financial Information or Risk Factors evidence is still missing, the IPO fails the evidence gate rather than encouraging the model to guess.

## News limitation

The no-key V1 collector uses Google News RSS headlines/snippets. These are deliberately labelled as lower-confidence evidence than RHP/NSE data. The architecture is pluggable: a future GNews/NewsAPI/paid source can replace this collector without changing the analyst or PDF layers.

## Exchange verification limitation

V1 uses NSE as the deterministic official verification/enrichment source for mainboard issues and also retains provider-reported exchange metadata. This covers the normal NSE/BSE mainboard flow. If you later want BSE-only issues or SME coverage, add a `BSEVerifier` behind the same verification contract rather than mixing BSE scraping into `main.py`.

## Extending to SME later

The provider contract already accepts `include_sme`. V1 explicitly calls it with `False`. When SME support is added, use a separate SME analysis policy because liquidity, market-making, lot sizes and risk characteristics differ materially from mainboard IPOs.

## Important note

This project produces research synthesis for educational use. It should not be treated as personalized investment advice or an automatic investment decision engine.
