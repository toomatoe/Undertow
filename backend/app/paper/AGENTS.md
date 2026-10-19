# backend/app/paper: hypothetical paper portfolio

What an equal-weight book built from the forward signal journal (`app/journal/`) would have done. It is a
calculation over journal rows plus cached prices: **hypothetical, not traded, not investment advice**. It replaces
the old "Trading (planned)" idea in the UI.

**No execution code, ever.** There is no account, no broker client, no order object and no network call in this
package. `tests/test_paper_portfolio.py::test_paper_package_has_no_execution_code` greps every `.py` file here for
`order` (other than SQL `order_by`), `broker`, `submit` and `alpaca` and fails on any hit, so keep those words
out of code and comments too.

## Files

| File | What |
|---|---|
| `service.py` | `build_portfolio(session, data_dir, *, notional=10_000, max_concurrent=20, hedge=False, today=None, price_loader=None) -> dict`; `CachedPrices` (per-entry cache-only price reads), `cached_series(data_dir, ticker)`; `LABEL` |

## Rules (`build_portfolio`)

- **One position per JournalEntry** at the journal's own entry: the day 0 + 1 close (`entry_date`, set by
  `journal.service.mark`, same timing as the backtest base case). Fixed notional, equal weight.
- **Side** from the entry's `direction`: `+` long, `-` short. `?` signals have no expected direction and open no
  position (counted in `totals.undirected`).
- **Hold** for `journal.service.evaluation_horizon(signal)` trading days of the stock's own calendar: 5 for
  `insider_cluster_purchase` (the forward test), 20 otherwise. An open position is marked to the latest close.
  If the series ends more than `journal.DATA_ENDED_AFTER_DAYS` before today and before the horizon, the position
  closes at the last close; a short pays the backtest's `delist_penalty` on top (never book a delisting gain).
- **Capacity:** entries are processed by entry day; while `max_concurrent` positions are open a new entry is
  skipped (`totals.skipped_capacity`). A position exiting on day d frees its slot for entries on day d.
- **Costs (never copy the numbers, import them):** round trip `research.eventstudy.COSTS[bucket]`; shorts pay
  borrow `apr x days_held / backtest.engine.TRADING_DAYS`, where apr = the journal row's recorded IBKR
  `borrow_fee` when present, else `research.eventstudy.BORROW_APR[bucket]`. Open positions carry half the round trip.
  Unknown buckets fall back to `small`.
- **Hedge** (`hedge=True`): an equal-notional opposite IWM leg per position, paying
  `backtest.engine.StrategyConfig().hedge_cost`. Without a cached IWM series the result is empty with a reason.
- **Prices (chosen per entry, not per ticker):** `journal.service.mark` writes `{ticker}_{start}_{end}.json`
  under `{data_dir}/prices_live` with a start that moves forward as older entries complete, so the newest file
  may not cover an old entry. `CachedPrices` lists a ticker's files once and loads them lazily via
  `research.prices.load_prices(..., offline=True)`; `_pick` uses, per entry, the newest file containing the
  entry day that also reaches the horizon (else the newest containing the entry day). The same rule picks each
  position's IWM hedge series. Files are never merged: one file per position keeps adjusted closes on one basis.
  A row with no covering series is `unpriced` and excluded with a count. Rows the journal has not priced yet
  (`waiting`) count as `pending`. `cached_series(data_dir, ticker)` returns just the newest series.
- **Capital** = notional x max_concurrent; `return_pct = pnl / capital`; `hit_rate` = closed positions with net
  return > 0.

## Output

`{as_of, label, assumptions {notional, max_concurrent, hedge, starting_capital, cost_model, horizons},
equity_curve [{date, equity, open_positions}] (union of the calendars of every position series, hedge series and the newest IWM file),
totals {pnl, return_pct, n_closed, n_open, hit_rate, skipped_capacity, unpriced, pending, undirected},
by_signal [{signal, label, direction, horizon, forward_test, forward_test_label, n, n_closed, pnl, mean_return_net, hit_rate}],
positions (most recent 50: ticker, signal, side, size_bucket, horizon, entry_date, exit_date|null, status, net_return, pnl),
empty_reason}`. An empty or young journal returns the same shape with empty lists and an `empty_reason`.
`label` is always `LABEL`; the UI must show it.

## API

`GET /api/paper-portfolio?hedge=false&max_concurrent=20` (main.py; `max_concurrent` 1..100, notional fixed
server-side as `PAPER_NOTIONAL`). Public, read-only, rate-limited by the middleware. Cached in
`state.paper_cache` per (ET date, hedge, max_concurrent) for `PAPER_TTL_SECONDS` (600). Response model
`PaperPortfolioOut` in schemas.py; mirrored in `frontend/src/lib/api.ts` (`api.paperPortfolio`). UI: `/paper`
(`frontend/src/app/paper/`, `components/portfolio/`); `/trading` redirects there.

## Tests

`tests/test_paper_portfolio.py`: long and short P&L with costs and bucket vs recorded borrow, 5-day vs 20-day
horizon, open-position marking, max-concurrent skip, IWM hedge leg, unpriced/pending/undirected counts, short
data-ended penalty, an old entry priced from an older cache file (and its IWM hedge leg) when the newest file starts after it, empty and young journal, endpoint shape via TestClient reading real cache files with
`httpx.get` patched to fail (proves no network), the hypothetical label, and the no-execution-code grep.
