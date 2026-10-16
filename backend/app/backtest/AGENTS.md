# backend/app/backtest — portfolio backtester

Simulates trading a filing-signal strategy as a real portfolio, with costs, borrow,
liquidity limits and random borrow luck. It then decides whether the strategy is
ready for paper trading or real money. The only strategy so far is
`nano_offering_short`: short companies with under $50M public float after a
424B4/424B5 (priced offering), hedged with IWM.

Read `../research/AGENTS.md` first. The event study there found the signal; this
module checks whether it can be traded.

## Files

| File | What it does |
|---|---|
| `universe.py` | `PERIODS` (A = Oct 2020–Aug 2023, out-of-sample; B = Oct 2023–Aug 2026, discovery), `build_universe()` → every 424B4/5 by a nano-cap company in the period, plus coverage counts. `PRICE_START/END` fix one shared price-cache window. |
| `engine.py` | `StrategyConfig` (every assumption in one frozen dataclass) and `simulate()`, the daily loop. Produces a `SimResult`: equity curve, exposure, trade log, skipped-signal log. |
| `stats.py` | Sharpe/Sortino/drawdowns, PSR, DSR (deflated against all configs ever tried), MinTRL, block bootstrap, monthly/yearly returns, trade stats. Pure Python, no numpy. |
| `report.py` | `build_report()` runs everything and writes `data/backtests/report_latest.json`. Also the run log (`data/backtests/runs.jsonl`), readiness gates, verdict, live projection and borrow check. CLI: `python -m app.backtest.report`. |
| `borrow.py` | Archives IBKR's public shortable-stocks file (`ftp2.interactivebrokers.com`, user `shortstock`) to `data/borrow/usa_*.txt.gz`, at most once per 12h. The API scheduler calls `snapshot()` after each ingest cycle. `parse()`, `latest()`, `status()`. |
| `warm.py` | Pre-fetches SEC submissions and prices for both periods. Slow the first time (around 20 min), cached afterwards. |

## The daily loop (engine.simulate)

1. Mark each open short to today's adjusted close. Charge one day of borrow (`borrow_apr / 252` × notional).
2. Exit, checked in this order:
   - **Stop:** close ≥ entry × (1 + `stop_loss`); filled `stop_slippage` worse.
   - **Recall:** random draw < `recall_prob`; filled `recall_penalty` worse.
   - **Time:** `hold_days` reached.
   - **Data ended:** delisting or halt; covered at last price + `delist_penalty`.
3. Enter today's events, applying these filters in order:
   - already short → `max_positions` → raw price ≥ `min_price` → 20-day **median** dollar volume ≥ `min_adv` → random borrow `availability` → size = min(`position_pct` × equity, `max_adv_pct` × ADV) → `max_gross_short`.
   - Every rejection is logged with its reason in `SimResult.skipped`.
4. Record equity, gross exposure and position count.

Each fill pays half of `cost_round_trip × cost_mult` (and `hedge_cost` for the IWM leg).

## Invariants: don't break these

- **Returns use adjusted closes. The price floor uses `raw_close`** (the unadjusted price, recovered from Yahoo split events in `research/prices.parse_chart`). Nano caps reverse-split constantly, so a $0.30 stock can look like $3.60 once adjusted.
- **ADV is measured *before* entry, as a median.** The offering day's volume spike would overstate capacity.
- **Never credit a delisting to a short.** Delisted names go to OTC, borrow gets recalled, and buy-ins happen.
- **Size is point-in-time:** Q2 public float of the year *before* the period (`Period.float_year`).
- **Day 0 comes from EDGAR acceptance time** (`research.eventstudy.day0_index`). The base case enters one close later (`entry_delay=1`), because Rule 201 usually blocks shorting into the day-0 drop.
- **Every simulation is appended to the run log.** Each entry has `kind`:
  - `search`: the base case and the walk-forward grid. These are attempts to find a better strategy.
  - `robustness`: stress tests, Monte Carlo seeds, capacity, waterfall and borrow sensitivity. These check the same strategy.

  DSR deflates against the distinct `(period, trial_key)` pairs among search runs ever logged. `trial_key` is the config without the seed, because a different random seed is luck, not a new idea. Legacy entries without `kind` count as search when their label is `base` or starts with `walk-forward` (`is_search`). Never delete or rotate `runs.jsonl` to make results look better.
- **The base config was fixed before the first backtest ran,** from the event study plus the methodology research summarized in `report.STRESS`/`StrategyConfig` comments. Change it only with a written reason; never because a result looked bad.

## Report sections beyond the base run

- `waterfall` (per period): starts from `FRICTIONLESS` and adds one friction per step (`WATERFALL`) until the config equals `BASE`. An assert enforces that the last step is exactly the base. This answers "where does the edge go?".
- `borrow_sensitivity` (per period): the base case at each fee in `BORROW_GRID`, plus the interpolated `breakeven_apr`. `0.0` means it loses even with free borrow; `None` means it never crosses zero in the range.
- `borrow_check`: today's IBKR snapshot for issuers from the last 6 months of period B, compared with the assumed availability and fee. Treat it as a lower bound: fees right after an offering are likely higher, and today's list only covers survivors.
- `key_finding`: a generated plain-English paragraph (gross edge → biggest cost → break-even → borrow check). The UI shows it under the verdict, so keep its logic honest when changing it.
- `monte_carlo`: base case over `MC_SEEDS`, giving p05/p50/p95 of return, Sharpe and drawdown.
- `walk_forward`: picks hold days and stop on A only, then tests the pick on B.

## Readiness gates (report.readiness)

| Kind | Gates | Rule |
|---|---|---|
| Research | Out-of-sample Sharpe ≥ 0.5 and return > 0 (period A); DSR ≥ 0.95; max drawdown ≤ 30%; worst-case stress Sharpe > 0; 5th-percentile Monte Carlo Sharpe > 0; half-unborrowable return > 0; ≥ 100 trades; price coverage ≥ 80%; fill rate at $100k ≥ 50% | Computed from the backtest. |
| Operational | Real borrow data; paper trading ≥ 3 months; risk controls | Always `pending` until built. |

`verdict()` returns `not_ready` if any research gate fails. Otherwise it returns
`paper_next`, which means "go and paper trade". **No code path says "ready for real money".**

## Running

```bash
docker compose build -q api
docker compose run --rm api python -m app.backtest.warm     # first time only
docker compose run --rm api python -m app.backtest.report   # about 5-10 min once cached
docker compose restart api                                  # optional: the API reads the file on request
```

API: `GET /api/backtest/report`, `GET /api/backtest/runs?limit=`, `GET /api/backtest/borrow`.
The UI lives at `frontend/src/app/backtest/`.

Tests: `backend/tests/test_backtest.py` uses synthetic price paths with known answers (costs, borrow, stop
slippage, the raw-price floor, delisting penalty, liquidity and gross limits, hedge, stats, split unadjusting,
borrow-file parsing).

## Adding a strategy

1. Write an event source that returns objects with the `OfferingEvent` fields: `ticker`, `accepted_et`, `form`, `filing_url`, `public_float`. A Form 4 insider-buy universe would be the natural next one.
2. Add a `STRATEGY` dict and base config in a new report module, or parameterize `report.py` by strategy id.
3. Long strategies need a sign flip in `engine.simulate`, which is short-only today: `shares` is the short count and P&L is `shares × (entry − exit)`.
4. Pre-register the base config and gates in the docstring *before* running.

## Known limits

- Daily closes only. Intraday squeezes, halts and the Rule 201 uptick constraint are approximated by delay, stop slippage and penalties.
- Borrow availability is a coin flip per trade. Replace it with the IBKR archive once it has ≥ 90 days.
- The hedge has beta = 1, not a fitted beta.
- Yahoo prices are personal-use only and lack most delisted names. Coverage is reported, not fixed.
