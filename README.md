# QuantDesk

**Small-cap event intelligence:** live SEC filing signals for companies under $2B, each shown with the evidence on how similar stocks moved afterwards.

Why this niche (details in [docs/FEASIBILITY.md](docs/FEASIBILITY.md)):
- Selling research tools has the clearest record of making money in this space. Retail trading bots mostly don't.
- The edges that survive in the literature are concentrated in small, illiquid stocks: LLM news sentiment, post-earnings drift, ML predictability. Big funds can't trade them at size.
- SEC filings are free and public domain, so a product built on them avoids most news-licensing costs.
- Small-cap traders are badly served: Bloomberg is priced for institutions, and retail apps focus on large caps.

**Status:** News, Signals, Track record, Newsletter, Edge Lab and Backtest tabs work, with real-time Discord alerts, server-rendered ticker pages (dilution/runway, SEO metadata, sitemap) and an automatic weekly newsletter. Research (AI assistant) and Trading (paper trading) are planned.

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

**Real-time alerts** (`backend/app/alerts/`)
- EDGAR is polled every 30 seconds on its own loop.
- New signal filings go to a Discord webhook when they are severity 2+ and either from a nano/micro/small cap or on the watchlist.
- Each alert carries the Edge Lab stat and its own detection latency.
- Every decision is logged at `/api/alerts`.
- Set `DISCORD_WEBHOOK_URL` in `.env` to turn it on, then call `POST /api/alerts/test` to check delivery.

**Track record tab** (`backend/app/journal/`)
- Every signal filing is recorded the moment it appears, append-only, priced at the same close the backtest would trade, and compared with IWM over 1/5/20 trading days.
- Results sit next to what the Edge Lab expected.
- The IBKR borrow fee at record time is captured, which is the data a fee-aware strategy needs.
- It started on Oct 13, 2026, with 141 signals recorded on day one.

**Dilution, runway, short interest and halts on ticker pages** (`backend/app/fundamentals/`, `backend/app/sources/halts.py`)
- Cash (plus same-day short-term investments), trailing-12-month operating burn and months of runway, from SEC XBRL.
- Share-count change over 1 year, and every offering-type filing in the last 3 years.
- FINRA short interest (free, twice monthly): % of shares outstanding and days to cover.
- Trading halts from the Nasdaq Trader feed, polled every 30s, with reasons in plain English.
  - News and regulatory halts on small caps or watchlist names also alert on Discord. Constant volatility pauses alert only for watchlist names.
  - The Signals page shows a "Halts today" panel.

**Server-rendered ticker pages (SEO)** (`frontend/src/app/ticker/[symbol]/`)
- `/ticker/{SYMBOL}` is rendered on the server and cached for 15 minutes, so the content is in the initial HTML.
- A factual summary paragraph with explicit dates: size and public float, cash and runway, 1-year share change, priced offerings, short interest, latest filing signal, halts and mention count.
- Title, meta description, canonical URL, Open Graph tags and JSON-LD per ticker. Unknown or malformed symbols return a real HTTP 404.
- `/sitemap.xml` lists the static pages, every known company ticker with an article or filing in the last 180 days (`GET /api/tickers/sitemap`) and every archived newsletter issue. `/robots.txt` points at it and disallows `/api/`.
- Set `NEXT_PUBLIC_SITE_URL` in `frontend/.env.local` to the public origin (template: the frontend section at the bottom of the root `.env.example`).

**Newsletter tab: weekly "Small-Cap Filing Radar"** (`backend/app/newsletter/`, see its [AGENTS.md](backend/app/newsletter/AGENTS.md))
- Built automatically after each slow ingest cycle once a week is complete (Monday-Sunday, US Eastern), from our own data only.
- Sections: headline counts, top signal filings with the matching historical Edge Lab stat, dilution watch, serious halts, track-record progress, a research note from the latest backtest report, and the disclaimer.
- Archived as JSON, Markdown and email-safe HTML under `{DATA_DIR}/newsletters/`. An issue is never overwritten unless rebuilt with `--force`.
- `/newsletter` shows the archive and the latest issue; `/newsletter/{id}` (e.g. `2026-W41`) is a server-rendered issue page. Copy the Markdown or download the HTML to paste into Substack/Beehiiv; "Preview this week so far" builds the current week without saving it. No email sending yet.
- Impersonal facts and historical statistics only; every Edge Lab, backtest and journal number is labelled historical or hypothetical, and the rendered text is checked for advice words.
- Links in the issue use `PUBLIC_BASE_URL` (root `.env`).

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
| `backend/app/research/`, `backtest/`, `journal/`, `alerts/`, `fundamentals/`, `newsletter/` | Event study, backtester, track record, alerts, dilution/runway, weekly newsletter |
| `backend/app/main.py` | API + background scheduler (ingest, borrow snapshot, journal, newsletter) and fast EDGAR/halts poller |
| `frontend/src/` | Next.js App Router UI; ticker and newsletter pages are server-rendered for SEO |
| `docs/FEASIBILITY.md` | Research: strategies, languages, system design, data APIs |

## Run it

Requires Docker and Node 20+.

```bash
cp .env.example .env          # optional: add keys
docker compose up -d --build  # Postgres + API on :8000 (starts ingesting right away)
cd frontend && npm install && npm run dev   # UI on :3000
```

Frontend settings (optional) go in `frontend/.env.local`, not the root `.env`: copy the commented frontend section at the bottom of the root `.env.example` and uncomment the lines you need. For a public deployment set `NEXT_PUBLIC_SITE_URL` there and `PUBLIC_BASE_URL` in the root `.env` to the same origin.

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

Build a newsletter issue by hand (the scheduler does this automatically):

```bash
docker compose run --rm api python -m app.newsletter.build                       # last completed week
docker compose run --rm api python -m app.newsletter.build --week-end 2026-10-11 # a specific week (add --force to overwrite)
docker compose run --rm api python -m app.newsletter.build --preview             # current week so far, not saved
```

Backend tests:

```bash
docker compose run --rm api pytest -q
bash scripts/pytest.sh tests/test_api.py   # against the current source, no image rebuild
```

No Docker? The backend falls back to SQLite: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`.

## API

| Endpoint | |
|---|---|
| `GET /api/articles?q=&ticker=&source=&sentiment=&event_type=&min_relevance=&before=&limit=` | Feed, newest first; page with `before` |
| `GET /api/articles/{id}` | One article |
| `GET /api/tickers/trending?hours=24` | Most-mentioned tickers with average sentiment |
| `GET /api/tickers/{symbol}?days=30` | Ticker detail + daily coverage |
| `GET /api/tickers/sitemap?days=180` | Tickers with a known company (SEC company list) and an article or filing in the window, most recent first (`symbol`, `last_activity`, `items`, `size_bucket`) |
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
| `GET /api/journal?signal=&size=&status=` · `GET /api/journal/summary` | Forward track record |
| `GET /api/alerts` · `POST /api/alerts/test` | Alert config, latency, delivery log · test message |
| `GET /api/tickers/{symbol}/fundamentals` | Cash runway, share dilution, offering history, short interest |
| `GET /api/halts?symbol=&size=&hours=` | Trading halts with plain-English reasons |
| `GET /api/newsletter/issues` | Newsletter archive, newest first (id, week, headline counts) |
| `GET /api/newsletter/{id}` · `GET /api/newsletter/{id}.html` | One issue as JSON (+ `markdown`) · its email-safe HTML |
| `POST /api/newsletter/preview` | Current week so far (+ `markdown`, `html`), never saved |
| `GET /api/health` | Liveness check |

## Roadmap

Product priorities come from [docs/PRODUCT_RESEARCH.md](docs/PRODUCT_RESEARCH.md) (competitors, pricing, legal, distribution). Research priorities come from the backtest's readiness gates.

**Done**
1. ~~News tab~~
2. ~~Small-cap signals + Edge Lab~~
3. ~~Portfolio backtester with run log, stress tests, walk-forward and live-readiness gates~~ (Backtest tab)
4. ~~Forward signal journal / public track record~~ (Track record tab)
5. ~~30-second EDGAR polling + Discord alerts~~ (roadmap item 1, and Discord from item 2)
6. ~~Ticker page: dilution history, cash runway, short interest, halts~~ (roadmap item 4)
7. ~~Legal pack drafts + Methodology page + site footer~~ (roadmap item 8, pending lawyer review)
8. ~~Server-rendered SEO ticker pages, sitemap.xml, robots.txt~~ (part of roadmap item 9)
9. ~~Weekly newsletter: automatic build, archive, Markdown/HTML export, Newsletter tab~~ (part of roadmap item 9; email delivery not built)

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
- Signal × AI-flag studies (e.g. offerings with "ATM program" vs priced deals). Needs an API key and point-in-time scoring.
- Research agent: Claude with read-only tools over news, filings and backtests. It never trades.

## Notes

- Free data tiers are mostly for **personal / non-commercial** use. The UI shows headlines and links out, never republished full text. A public or paid version needs commercial licenses.
- Enrichment defaults to `claude-opus-5-5`, with server-side refusal fallback on. Set `ENRICH_MODEL=claude-haiku-5-5` to cut cost about 40x. `ENRICH_MAX_PER_CYCLE` caps spend per cycle.
- Prices for research come from Yahoo's unofficial chart endpoint, for personal use only (throttled, cached, never redistributed). Use a licensed feed for anything public.
- Tables are created with `create_all`, plus a stopgap that adds new nullable columns. Move to Alembic before real data matters.
