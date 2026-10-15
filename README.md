# QuantDesk

**Small-cap event intelligence:** live SEC filing signals for companies under $2B, each shown with the evidence on how similar stocks moved afterwards.

Why this niche (details in [docs/FEASIBILITY.md](docs/FEASIBILITY.md)):
- Selling research tools has the clearest record of making money in this space. Retail trading bots mostly don't.
- The edges that survive in the literature are concentrated in small, illiquid stocks: LLM news sentiment, post-earnings drift, ML predictability. Big funds can't trade them at size.
- SEC filings are free and public domain, so a product built on them avoids most news-licensing costs.
- Small-cap traders are badly served: Bloomberg is priced for institutions, and retail apps focus on large caps.

**Status:** News, Signals and Edge Lab tabs work. Research (AI assistant) and Trading (paper trading) are planned.

> Research and education only. Nothing here is financial advice.

## What works now

**Signals tab**
- Live SEC filings that carry a signal: 8-K items (restatement, auditor change, delisting notice, bankruptcy, debt default, unregistered share sale, executive change…), priced offerings (424B4/5), S-1/S-3 registrations, and Schedule 13D activist stakes.
- Every ticker is sized by SEC public float: nano (<$50M), micro, small, mid, large. Defaults to companies under $2B.
- Severity ranking, signal-type filter and a watchlist.
- Each card shows the matching Edge Lab result, e.g. "Past nano caps: −15.6% vs index over 20d (−13.7% vs ordinary days), n=302".
- With an API key, the filing's actual document is summarized, and red flags (going concern, reverse split, ATM program, dilutive financing…) are extracted.

**Edge Lab tab**
- Event study (`backend/app/research/eventstudy.py`): after each signal type, did the stock beat or lag the index over 5 and 20 trading days, by size bucket, after realistic trading costs?
- The design is fixed up front: size measured before the window, timing by EDGAR acceptance time, market-adjusted returns, winsorized outliers, a Bonferroni correction across every test, and trade direction chosen before seeing results.
- Reports survivorship coverage, meaning how many sampled companies have since delisted.

### First results (Oct 2026 run)

21,842 filing events from 747 randomly sampled companies, Oct 2023 to Aug 2026, 102 signal × size × horizon tests:

- **One signal survives every check:** nano caps (public float under $50M) that price an offering (424B4/424B5).
  - They lag the index by **15.6%** over the next 20 trading days (median −20.4%, n=302, t=−6.7).
  - The same stocks on ordinary days lag by 2.0%, so the filing itself is worth **−13.7%** (t=−5.7).
  - Shorting at the day-0 close nets about **+8.7%** after 3% trading costs and roughly 4% estimated borrow.
  - This matches the long-standing literature on post-offering underperformance (Loughran & Ritter 1995) and is far larger at the nano end.
- **Close, but not past the multiple-testing bar:** unregistered share sales (8-K item 3.02) in micro and nano caps, at about −5% to −7% vs ordinary days (t ≈ −3.0 to −3.4, cutoff 3.49).
- **Large caps:** nothing. Every nominal effect disappears against the baseline.
- **Lead for a separate test:** in nano caps, "material agreement" 8-Ks drift −5.5% vs ordinary days (t=−3.9). These are likely financing deals. The trade direction was fixed in advance as long, so this does not count as a finding yet.

**Why this is a lead, not a strategy yet:**
- The 302 events come from only 74 serial-diluting companies, so they are not independent.
- About a quarter of sampled nano caps have since delisted and are missing from the data.
- Nano caps right after an offering are often hard or impossible to borrow.
- It is one sample from one period. The next step is an out-of-sample rerun (2020–2023, fresh companies) before anything goes near paper trading.

**News tab**

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

Run the event study (about 15 min, cached afterwards). The API picks up results on restart:

```bash
docker compose run --rm api python -m app.research.eventstudy
docker compose restart api
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
| `GET /api/signals?size=nano,micro,small&min_severity=&signal=&watchlist=` | Filing signals with historical evidence |
| `GET /api/signals/catalog` | Signal taxonomy |
| `GET /api/research/event-study` | Latest event-study results |
| `GET/PUT/DELETE /api/watchlist[/{symbol}]` | Watchlist |

## Roadmap

1. ~~News tab~~ ✅
2. ~~Small-cap signals + Edge Lab~~ ✅
3. Insider purchases (Form 4): the best-documented small-cap filing signal (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012). Needs per-filing XML parsing.
4. Signal × AI flag studies: e.g. 8-K item 2.02 split by AI sentiment, or offerings split by "ATM program" vs "priced deal". This needs an API key and point-in-time scoring.
5. Out-of-sample check: rerun the study on 2020–2023 and on a fresh company sample. Only signals that hold up go to paper trading.
6. Research agent: Claude with read-only tools (news search, prices, filings, backtests). Writes reports, never trades.
7. Data + backtest harness: Parquet/DuckDB history, walk-forward runs, cost model, log of every variant tested with deflated Sharpe.
8. Trend-following strategy on Nautilus Trader, then Alpaca paper trading behind a hard risk gate and kill switch.
9. News-sentiment overlay experiment, scored only on articles published after the model's training cutoff.

## Notes

- Free data tiers are mostly for **personal / non-commercial** use. The UI shows headlines and links out, never republished full text. A public or paid version needs commercial licenses.
- Enrichment defaults to `claude-opus-5-5`, with server-side refusal fallback on. Set `ENRICH_MODEL=claude-haiku-5-5` to cut cost about 40x. `ENRICH_MAX_PER_CYCLE` caps spend per cycle.
- Prices for research come from Yahoo's unofficial chart endpoint, for personal use only (throttled, cached, never redistributed). Use a licensed feed for anything public.
- Tables are created with `create_all`, plus a stopgap that adds new nullable columns. Move to Alembic before real data matters.
