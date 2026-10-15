# Algo Trading + Market Research App — Feasibility Report

*Compiled 2026-10-15 from four parallel research passes. Educational research, not financial advice. Figures marked (secondary) were not verified against the primary source.*

## TL;DR

- **Buildable? Yes.** A solo dev can ship a paper-trading bot, an honest backtester and a live news/research tab for **$0/month** on free tiers (Alpaca + SEC EDGAR + FRED + RSS).
- **"Make money fast"? The evidence says no.** Fewer than 1% of Taiwan day traders are reliably profitable after fees, and 97% of persistent Brazilian day traders lost money. Backtest Sharpe barely predicted live Sharpe across 888 Quantopian strategies (R² < 0.025). Documented edges run at Sharpe ≈ 0.4–1 and **shrink 26–58% after publication**. Fast returns need leverage, and leverage is how accounts get wiped out.
- **Is C++ the right language? Not for this.** Retail orders go over the internet to a broker API, and each round trip takes 10–100+ ms. Code running in 5 µs instead of 500 µs is invisible next to that. **Python** (Nautilus Trader engine, Rust core) for trading, **TypeScript/Next.js** for the UI. Move hot paths to Rust only if profiling demands it.
- **Where the money demonstrably is: selling tools.** Examples: TradingView ($3B valuation), Kraken buying NinjaTrader ($1.5B), QuantConnect SaaS, Alpaca BaaS, Hummingbot exchange fee-share. The research/news tab is the most product-shaped part of this idea.

## 1. What successful players actually exploit

| Who | Edge | Reachable solo? |
|---|---|---|
| Renaissance Medallion (~39% net/yr 1988–2018) | Thousands of tiny stat-arb signals, decades of cleaned data, PhD army | No |
| Jane Street (~$40B net trading rev 2025), Citadel Securities, HRT, Virtu | Market making, retail order flow, colocation, microwave links | No |
| Jump | Pure speed (bought land near CME for microwave towers) | No |
| Freqtrade / Nautilus / LEAN / Hummingbot (20–55k GitHub stars) | Open-source engines; same code for backtest and live | **Yes — build on these** |
| TradingView, QuantConnect, Alpaca, 3Commas, MQL5 market | Sell tools/data/infra to traders | Yes, as a business |

Lessons from failures:
- **Knight Capital (2012):** lost about $440M in 45 minutes. Dead code and a reused flag, plus a manual deploy that reached 7 of 8 servers.
- **Citi (2022):** a $444B fat-finger order with no hard block.
- **3Commas (2022):** about 100k exchange API keys leaked.
- **Mirror Trading International:** a "trading bot" that never existed; a $1.7B Ponzi.

## 2. Strategies with evidence (ranked for a solo builder)

| # | Strategy | Evidence | Why it fits |
|---|---|---|---|
| 1 | **Diversified trend following** (ETFs/futures, daily bars) | Profitable in every decade 1880–2016 (AQR); Sharpe ~0.4 after hedge-fund fees (secondary) | Low turnover, latency irrelevant, easy to test honestly, 60/40 tax treatment on futures |
| 2 | **Crypto funding-rate / basis carry (delta-neutral)** | Sharpe ~1.9 for BTC at retail costs in backtest (He, Manela et al.), but shrinking | Simple execution; main risk is the exchange itself and liquidation of the short leg |
| 3 | **Monthly multi-factor equity** (momentum + quality/value, buy/hold bands) | Factors replicate across 93 countries (Jensen, Kelly, Pedersen 2023) | Great testbed for the data/backtest pipeline |
| 4 | **LLM news-sentiment overlay** on #1 or #3 | GPT headline scores predict next-day drift, mostly small caps / bad news (Lopez-Lira & Tang); returns decay as adoption grows | Ties the news tab to trading; only as a *slow* overlay, scored post-training-cutoff |

**Avoid first:**
- **Market making:** you're up against co-located firms with better information.
- **Scalping / intraday reversal:** fees eat the edge.
- **Price-only deep learning:** overfitting magnet.
- **Leveraged short-options selling:** smooth backtests until a crash wipes you out.

**Testing discipline is the product:**
- Log every variant you try and apply the deflated Sharpe ratio. 45+ configs on 5 years of data can produce an in-sample Sharpe of 1 that is pure noise.
- Walk-forward testing, then a one-time holdout, then 3+ months of paper trading, then small size.
- Use point-in-time data and include delisted names.
- Reject any edge that dies at 2× the assumed costs.
- Size positions with ¼–½ Kelly or volatility targeting.

## 3. US rules that matter (2026)

- **PDT $25k rule replaced.** SEC approved on 2026-04-14 and it took effect 2026-06-04 (FINRA RN 26-10), replaced by intraday margin requirements. Brokers can phase it in until 2027-10-20, so check yours.
- **Wash sales:** apply to stocks and options, and a high-turnover bot generates many of them. They still don't apply to crypto as of mid-2026.
- **Taxes:** short-term gains are taxed as ordinary income. Section 1256 futures get 60/40 treatment. 1099-DA cost-basis reporting for crypto starts with 2026 sales.
- **Offshore perpetual futures exchanges:** mostly unavailable to US persons, which limits basis trades.

## 4. Data, broker and news stack (free to start)

| Need | Pick | Notes |
|---|---|---|
| Execution + paper | **Alpaca** | Stocks, options and crypto paper trading; same code path as live; 200 req/min |
| Market data | Alpaca free (IEX real-time, crypto, 7+ yrs bars) + Finnhub free | IEX is about 2–3% of volume; first upgrade is Alpaca SIP at $99/mo |
| News | Alpaca/Benzinga news WebSocket (free), Finnhub news, SEC EDGAR 8-Ks, FRED, GDELT, RSS | Show headlines + links; full-text redistribution needs a license |
| Skip | Schwab (no API paper, 7-day re-auth), IBKR (needs funded account), NewsAPI free (dev-only, 24h delay), X API (paid), yfinance in production | |

Free tiers are mostly **personal / non-commercial**. Going public or paid means commercial data and news licenses, usually hundreds to thousands per month.

## 5. Recommended architecture (v1)

```
 ┌──────────── Data adapters (Alpaca WS/REST, EDGAR, RSS, FRED) ────────────┐
 │                         normalized events (UTC)                          │
 ▼                                                                          ▼
Event bus (in-process asyncio) ──► Strategy engine ──► order INTENTS     News pipeline
        │                                                  │             dedupe → ticker tag →
        │                                                  ▼             LLM summary/sentiment
        │                                      Risk gate (hard limits,        │
        │                                      daily loss stop, kill switch)  ▼
        │                                                  │             Postgres + pgvector
        ▼                                                  ▼                  │
Event log (replayable) ◄────────────── OMS (client IDs, state machine,       │
        │                              broker reconciliation)                 │
        ▼                                                  │                  │
Backtester (same strategy + risk code,          Broker adapter (paper/live)   │
simulated fills)                                                              ▼
                     FastAPI ──► Next.js UI: News tab · Research agent · Positions · Kill switch
```

| Layer | Choice |
|---|---|
| Engine / backtest | Python 3.12 on **Nautilus Trader** (Rust core, Python strategies), polars/numpy |
| Storage | Postgres + TimescaleDB (orders, fills, events), Parquet + DuckDB (history), pgvector (news) |
| Web | FastAPI + Next.js (TypeScript), SSE/WebSocket for live headlines |
| Research agents | Claude API with read-only tools (search news, query prices, run a backtest). **Never places orders.** Signals go through backtest and the risk gate. |
| Ops | Docker Compose on one VM in us-east (~$20–80/mo est.), secrets manager, Telegram alerts, trade-only API keys with IP allowlist, kill switch in both UI and CLI |

**When to use Rust/C++:** only after profiling shows strategy code is a meaningful share of the broker round trip, or CPU-bound parameter sweeps outgrow numba/polars. Add PyO3 modules for the hot functions, not a rewrite. C++/FPGA only makes sense with direct market access and colocation, which is a different business.

## 6. Suggested build order

1. **Research tab first** (lowest risk, highest product value): ingest Alpaca news + EDGAR + RSS, LLM summaries/sentiment, ticker pages.
2. **Data + backtest harness:** Parquet history, walk-forward runner, cost model, variant log with deflated Sharpe.
3. **Strategy #1 (trend following)** in backtest, then on the Alpaca paper account behind the risk gate.
4. **Monitoring + kill switch + reconciliation** before anything runs unattended.
5. **Experiments:** news-sentiment overlay, crypto basis carry (paper only).
6. Real money only after 3+ months of paper results that match the backtest, at small size.

## Sources (selection)

- McLean & Pontiff 2016 — https://www.gwern.net/doc/economics/2016-mclean.pdf
- Barber, Lee, Liu, Odean (Taiwan) — https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf
- Chague et al. (Brazil) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
- Quantopian backtest vs live — https://quantpedia.com/quantopians-academic-paper-about-in-vs-out-of-sample-performance-of-trading-alg/
- AQR century of trend following — https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
- Lopez-Lira & Tang — https://arxiv.org/abs/2304.07619v6
- Perpetual futures fundamentals — https://arxiv.org/abs/2212.06888v6
- Backtest overfitting — https://papers.ssrn.com/abstract=2326253
- FINRA RN 26-10 (PDT replacement) — https://www.finra.org/rules-guidance/notices/26-10
- Knight Capital (SEC) — https://www.sec.gov/news/press-release/2013-222
- Nautilus architecture — https://nautilustrader.io/docs/latest/concepts/architecture
- Alpaca data/paper — https://alpaca.markets/data , https://docs.alpaca.markets/docs/paper-trading
- Massive (ex-Polygon) pricing — https://massive.com/pricing
- CFTC on AI trading bots — https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/aitradingbots.html
