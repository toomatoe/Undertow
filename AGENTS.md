# QuantDesk: agent guide (start here)

QuantDesk is small-cap event intelligence: live SEC filing signals for companies under $2B public float,
each shown next to an event-study result on how similar stocks moved afterwards.
It also has a live market news feed (EDGAR, RSS, optional Alpaca/Benzinga) with optional Claude enrichment.
Research and education only; it does not trade.

Read this file, then only the AGENTS.md of the folder you are working in.

## Directory map

| Path | Purpose | Guide |
|---|---|---|
| `backend/` | FastAPI app, DB, tests, Dockerfile | [backend/AGENTS.md](backend/AGENTS.md) |
| `backend/app/sources/` | One adapter per data source, each returns `RawArticle` | [sources/AGENTS.md](backend/app/sources/AGENTS.md) |
| `backend/app/pipeline/` | Ingest cycle: dedupe, ticker tagging, company sizes, signal taxonomy, LLM enrichment, SSE | [pipeline/AGENTS.md](backend/app/pipeline/AGENTS.md) |
| `backend/app/research/` | Event study (`eventstudy.py`) and Yahoo price loader (`prices.py`) | [research/AGENTS.md](backend/app/research/AGENTS.md) |
| `backend/app/backtest/` | Portfolio backtester, run log, readiness gates, IBKR borrow archiver | [backtest/AGENTS.md](backend/app/backtest/AGENTS.md) |
| `backend/app/journal/` | Forward signal journal: live track record vs Edge Lab expectations | [journal/AGENTS.md](backend/app/journal/AGENTS.md) |
| `backend/app/alerts/` | 30-second EDGAR polling + Discord alerts with latency log | [alerts/AGENTS.md](backend/app/alerts/AGENTS.md) |
| `backend/app/fundamentals/` | Cash runway and dilution history from SEC XBRL + filings | [fundamentals/AGENTS.md](backend/app/fundamentals/AGENTS.md) |
| `backend/tests/` | pytest suite (in-memory SQLite, no network) | covered in backend/AGENTS.md |
| `frontend/` | Next.js 15 App Router UI | [frontend/AGENTS.md](frontend/AGENTS.md) |
| `docs/` | Feasibility research, product research, published event-study results | [docs/AGENTS.md](docs/AGENTS.md) |
| `docker-compose.yml` | `db` (pgvector/pgvector:pg17) + `api` (built from `backend/`) | |
| `.env.example` | Every optional env var with comments; copy to `.env` (git-ignored) | |
| `.claude/launch.json` | Preview config: frontend dev server on :3000 | |

## Run everything

```bash
cp .env.example .env                 # optional; app runs on free sources without keys
docker compose up -d --build         # Postgres :5432 + API :8000, ingests on startup
npm --prefix frontend install        # first time only
npm --prefix frontend run dev        # UI on :3000 (API base: NEXT_PUBLIC_API_URL, default http://localhost:8000)
```

Python is not installed on the host. Run all Python through the `api` container:

```bash
docker compose build api                                       # code is COPYed into the image: rebuild after edits
docker compose run --rm api pytest -q                          # backend tests
docker compose run --rm api python -m app.research.eventstudy  # event study (~15 min first run, cached after)
docker compose restart api                                     # API reloads event_study.json at startup
```

## Conventions (non-negotiable)

- **SEC User-Agent comes from config** (`settings.sec_user_agent`, env `SEC_USER_AGENT`). Pass it through;
  never hard-code a personal email or any contact string in code, tests or docs.
- **Research prices are Yahoo, personal use only** (`backend/app/research/prices.py`). Throttled, cached,
  never redistributed or served by the API. Anything public needs a licensed feed.
- **Agents never place orders.** No broker order code paths. Alpaca keys are paper keys used for news only.
- **No secrets in git.** Keys live in `.env` (ignored by `.gitignore`). Never commit live keys or `backend/data/`.
- Event-study design changes happen before looking at results, never after (see research/AGENTS.md).
- UI shows headlines and links out; never republish full article text.

## How to add...

**A data source**
1. `backend/app/sources/<name>.py`: class with `name: str` and `fetch() -> list[RawArticle]` (contract in sources/AGENTS.md).
2. Register it in `build_sources()` in `backend/app/pipeline/ingest.py` (this also makes it appear in `/api/status`).
3. Settings in `backend/app/config.py` (+ an `*_enabled` property if optional) and a commented line in `.env.example`.
4. If it introduces a new `source` value: `SOURCE_LABELS` in `frontend/src/lib/format.ts` and the source `<select>` in `frontend/src/components/NewsFeed.tsx`.
5. Parser test in `backend/tests/` with a canned payload (no network).

**A filing signal**
1. Add a `SignalDef` to `ITEM_SIGNALS` (8-K item) or `FORM_SIGNALS` (form) in `backend/app/pipeline/signals.py`.
2. New form: also add it to `EVENT_FORMS` (signals.py) and `FORM_EVENTS` (`backend/app/sources/edgar.py`).
3. Live alerts, `/api/signals/catalog` and the event study pick it up via `signals_for_filing()`. Adding a signal
   changes the Bonferroni test count, so it is a design change: decide it, then rerun the study.

**A page**
1. `frontend/src/app/<route>/page.tsx` (`"use client"` if it uses hooks).
2. Add a tab to `TABS` in `frontend/src/components/Nav.tsx`.
3. New endpoint: route in `backend/app/main.py`, response model in `backend/app/schemas.py`, mirrored type +
   method in `frontend/src/lib/api.ts`.

## Where to start for task X

| Task | Start in |
|---|---|
| New API endpoint or filter | `backend/app/main.py`, `backend/app/schemas.py`, `frontend/src/lib/api.ts` |
| New DB column | `backend/app/models.py` (must be nullable; see stopgap migration in backend/AGENTS.md) |
| Env var / setting | `backend/app/config.py`, `.env.example` |
| Feed is missing or duplicating stories | `backend/app/pipeline/dedupe.py`, `ingest.py` (`is_duplicate`) |
| Wrong or missing tickers | `backend/app/pipeline/tickers.py`, `sources/edgar.py` (`tickers_for_cik`) |
| Wrong size bucket | `backend/app/pipeline/companies.py` (`BUCKETS`, `load_latest_floats`) |
| EDGAR parsing / 13D handling | `backend/app/sources/edgar.py` (`parse_entry`) |
| LLM summary, sentiment, flags, model choice | `backend/app/pipeline/enrich.py` |
| Live updates in the UI | `backend/app/pipeline/events.py`, `/api/stream` in `main.py`, `NewsFeed.tsx` |
| Event-study method or results | `backend/app/research/eventstudy.py`, `docs/results/` |
| Evidence line on signal cards | `load_study()` / `to_out()` in `main.py`, `ArticleCard.tsx` |
| Edge Lab charts | `frontend/src/app/lab/page.tsx`, `--div-*` tokens in `globals.css` |
| Strategy backtests | `backend/app/backtest/` (its own AGENTS.md) |
| Feasibility / product docs | `docs/` |
