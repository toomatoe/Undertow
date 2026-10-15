# QuantDesk

A market news and research desk, built as the first step toward an evidence-driven paper-trading system.

**Status:** v1 = the News tab. Research (AI assistant) and Trading (backtest + paper trading) are planned; see [docs/FEASIBILITY.md](docs/FEASIBILITY.md) for the research behind the plan.

> Research and education only. Nothing here is financial advice.

## What works now

- **Live news feed** from free sources:
  - SEC EDGAR 8-K filings, mapped to tickers and event types (earnings, M&A, deals, management changes…)
  - RSS: CNBC, MarketWatch, Seeking Alpha, Investing.com, PR Newswire, Federal Reserve
  - Alpaca/Benzinga news (optional, free with Alpaca paper keys)
- **Dedupe:** canonical URL hash, plus a headline hash to catch syndicated copies.
- **Ticker tagging:** cashtags and exchange notation like `(NASDAQ: GOOGL, GOOG)`, checked against the SEC's ~10k-company list. SEC filings get their ticker from the CIK.
- **AI enrichment (optional):** one-line summary, sentiment from -1 to 1, event type, relevance, and tickers the article is about. Uses Claude structured outputs; each result stores the model that produced it.
- **UI:** filterable feed, live updates over server-sent events, trending tickers, per-ticker page with coverage by day, source health panel.

## Architecture

```
sources (EDGAR, RSS, Alpaca) → dedupe → ticker tagging → Postgres → LLM enrichment
                                                            │
                     FastAPI (REST + SSE) ──────────────────┘ → Next.js UI
```

| Path | What |
|---|---|
| `backend/app/sources/` | One adapter per source, each returning `RawArticle` |
| `backend/app/pipeline/` | `dedupe`, `tickers`, `enrich`, `ingest` (one cycle), `events` (SSE pub/sub) |
| `backend/app/main.py` | API + background scheduler |
| `frontend/src/` | Next.js App Router UI |
| `docs/FEASIBILITY.md` | Research: strategies, languages, system design, data APIs |

## Run it

Requires Docker and Node 20+.

```bash
cp .env.example .env          # optional: add keys
docker compose up -d --build  # Postgres + API on :8000 (starts ingesting right away)
cd frontend && npm install && npm run dev   # UI on :3000
```

Backend tests:

```bash
docker compose run --rm api pytest -q
```

No Docker? The backend falls back to SQLite: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`.

## API

| Endpoint | |
|---|---|
| `GET /api/articles?q=&ticker=&source=&sentiment=&event_type=&min_relevance=&before=&limit=` | Feed, newest first; page with `before` |
| `GET /api/articles/{id}` | One article |
| `GET /api/tickers/trending?hours=24` | Most-mentioned tickers with average sentiment |
| `GET /api/tickers/{symbol}?days=30` | Ticker detail + daily coverage |
| `GET /api/status` | Counts, enabled features, last run per source |
| `POST /api/ingest` | Run a cycle now |
| `GET /api/stream` | SSE: `article`, `article_updated` |

## Roadmap

1. ~~News tab~~ ✅
2. Research agent: Claude with read-only tools (news search, prices, filings, backtests). Writes reports, never trades.
3. Data + backtest harness: Parquet/DuckDB history, walk-forward runs, cost model, log of every variant tested with deflated Sharpe.
4. Trend-following strategy on Nautilus Trader, then Alpaca paper trading behind a hard risk gate and kill switch.
5. News-sentiment overlay experiment, scored only on articles published after the model's training cutoff.

## Notes

- Free data tiers are mostly for **personal / non-commercial** use. The UI shows headlines and links out, never republished full text. A public or paid version needs commercial licenses.
- Enrichment defaults to `claude-opus-5-5`, with server-side refusal fallback on. Set `ENRICH_MODEL=claude-haiku-5-5` to cut cost about 40x. `ENRICH_MAX_PER_CYCLE` caps spend per cycle.
- Tables are created with `create_all`. Add Alembic migrations before the schema needs to change on real data.
