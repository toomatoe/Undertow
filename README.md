# QuantDesk

**Small-cap event intelligence:** live SEC filing signals for companies under $2B, each shown with the evidence on how similar stocks moved afterwards.

Why this niche (details in [docs/FEASIBILITY.md](docs/FEASIBILITY.md)):
- Selling research tools has the clearest record of making money in this space. Retail trading bots mostly don't.
- The edges that survive in the literature are concentrated in small, illiquid stocks: LLM news sentiment, post-earnings drift, ML predictability. Big funds can't trade them at size.
- SEC filings are free and public domain, so a product built on them avoids most news-licensing costs.
- Small-cap traders are badly served: Bloomberg is priced for institutions, and retail apps focus on large caps.

**Status:** News, Signals, Edge Lab and Backtest tabs work. Research (AI assistant) and Trading (paper trading) are planned.

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

**Backtest tab** (`backend/app/backtest/`, see its [AGENTS.md](backend/app/backtest/AGENTS.md))
- Simulates the nano-cap offering short as a real portfolio, day by day, over every 424B4/424B5 by a sub-$50M-float company:
  - Rule 201 entry delay, $1 raw-price floor, $200k median-volume floor, 5%-of-volume sizing.
  - 3% round-trip costs, 75%/yr borrow, 30% of names randomly unborrowable, 2%/day recalls.
  - Squeeze stop with slippage, no credit for delistings, IWM hedge.
- Two periods:
  - **A** (Oct 2020–Aug 2023): out-of-sample, untouched by the signal's discovery.
  - **B** (Oct 2023–Aug 2026): the discovery period.
- Analysis on top of the base run:
  - A friction waterfall showing where the edge goes.
  - 14 stress tests and a 20-seed Monte Carlo of borrow luck.
  - Bootstrap confidence intervals, and a Deflated Sharpe that counts every search attempt.
  - Walk-forward selection, a capacity table and a borrow-fee sensitivity curve.
- **Run log:** every simulation is appended to `data/backtests/runs.jsonl` and shown in the UI.
- **Live-readiness log:** 13 gates (research + operational) and a verdict. No code path can say "ready for real money" while operational gates are pending.
- **Borrow archiver:** saves IBKR's public shortable-stocks file daily, building the borrow history that doesn't exist for free.

### Backtest results (Oct 2026 run)

**Verdict: not ready for real money.** The strategy fails 8 of the 10 research gates.

| | Period A (out-of-sample) | Period B (discovery) |
|---|---|---|
| Signals → trades | 812 → 231 | 1,699 → 412 |
| Total return / CAGR | −33.4% / −12.8% | −11.5% / −4.0% |
| Sharpe / max drawdown | −1.24 / 39% | −0.24 / 33% |
| Gross edge per trade (no frictions) | +4.7% (median +8.7%) | +8.2% (median +14.3%) |
| Break-even borrow fee | loses even at 0% | ~76%/yr |

What the waterfall shows:
- The post-offering drift is real.
- Spread and borrow are the main costs. Borrow at 75%/yr costs about 5.8% per 20-day trade.
- Today's IBKR snapshot shows recent nano-cap issuers are cheaper to borrow than assumed: median 7%/yr, 75th percentile 36%, 97% borrowable.
- But out-of-sample, the strategy loses money even at zero borrow. Cheaper borrow alone would not rescue it.
- The edge is concentrated in 2023–2026. That is either a regime change or luck, and only fresh data can separate them.

Next steps:
- Keep archiving borrow data.
- Pre-register a fee-aware variant.
- Paper-trade it forward before any money is involved.

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

Run the backtest (first run about 20 min to download SEC histories and prices, then about 1 min):

```bash
docker compose run --rm api python -m app.backtest.warm
docker compose run --rm api python -m app.backtest.report
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
| `GET /api/backtest/report` | Latest backtest report (metrics, curves, trades, stress, readiness, verdict) |
| `GET /api/backtest/runs?limit=` | Run log: every simulation, newest first |
| `GET /api/backtest/borrow` | IBKR borrow archive status |

## Roadmap

Product priorities come from [docs/PRODUCT_RESEARCH.md](docs/PRODUCT_RESEARCH.md) (competitors, pricing, legal, distribution). Research priorities come from the backtest's readiness gates.

**Done**
1. ~~News tab~~
2. ~~Small-cap signals + Edge Lab~~
3. ~~Portfolio backtester with run log, stress tests, walk-forward and live-readiness gates~~ (Backtest tab)

**Product: path to first paying users**

DilutionTracker owns basic dilution alerts. The gap is *what happens next*: Edge Lab evidence on every alert, plus a public track record.

| # | Item | Why |
|---|---|---|
| 1 | Sub-60-second alert pipeline (poll EDGAR every 15–30s) | Speed is table stakes; competitors claim 60s. |
| 2 | Alert delivery: email, Discord webhook, Web Push | Nobody pays for a page they have to keep refreshing. |
| 3 | Watchlist + float filters on alerts | Already partly built; make it the core loop. |
| 4 | Ticker page: dilution history, cash runway, float, short interest (FINRA), halts (Nasdaq RSS) | The page traders keep open, and the SEO surface. |
| 5 | Public, timestamped signal track record | Trust, and a differentiator no competitor has. |
| 6 | Edge Lab stats on every alert | The unique angle. |
| 7 | Accounts + Stripe (free tier with delayed alerts, Pro about $29–39/mo) | Retail tools cluster at $25–75/mo. |
| 8 | Legal pack: impersonal-publisher posture, hypothetical-performance labels, lawyer review | FTC has fined trading-education firms; never personalize advice or trade for users. |
| 9 | Distribution: delayed-alert X/Discord bot, SEO ticker pages, weekly newsletter | How Quiver and Stock Analysis grew. |
| 10 | Monitoring, uptime alerts, licensed price data before showing prices publicly | Yahoo is personal-use only; licensed display data starts around $1.75k/mo. |

**Research**
- Out-of-sample rerun of the Edge Lab on 2020–2023 (the backtest's period A covers the offering signal).
- Insider purchases (Form 4): the best-documented small-cap filing signal (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012).
- Refit the borrow model from the IBKR archive after 90+ days of snapshots.
- Paper-trading journal: track every live signal as a hypothetical trade, as a forward test.
- Signal × AI-flag studies (e.g. offerings with "ATM program" vs priced deals). Needs an API key and point-in-time scoring.
- Research agent: Claude with read-only tools over news, filings and backtests. It never trades.

## Notes

- Free data tiers are mostly for **personal / non-commercial** use. The UI shows headlines and links out, never republished full text. A public or paid version needs commercial licenses.
- Enrichment defaults to `claude-opus-5-5`, with server-side refusal fallback on. Set `ENRICH_MODEL=claude-haiku-5-5` to cut cost about 40x. `ENRICH_MAX_PER_CYCLE` caps spend per cycle.
- Prices for research come from Yahoo's unofficial chart endpoint, for personal use only (throttled, cached, never redistributed). Use a licensed feed for anything public.
- Tables are created with `create_all`, plus a stopgap that adds new nullable columns. Move to Alembic before real data matters.
