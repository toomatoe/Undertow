# backend/app/research/: event study and prices

Question: after an SEC filing event, do stocks drift vs the index over 5 and 20 trading days, by size
bucket, after costs? Results feed the Edge Lab page and the evidence line on signal cards.

## The rule

**Change the design before looking at results, never after.** Any change to the sample, window, signal
taxonomy, horizons, costs, direction, baseline, winsorizing or significance test is a new design: write it
down (docstring + commit message), then run. Tweaking until something passes is data snooping, and the
Bonferroni correction does not protect against it. A signal that looks good but fails the pre-set rule is
a lead for a separate, pre-registered test (e.g. out of sample), not a result.

## Design (`eventstudy.py`) and its bias controls

| Control | How |
|---|---|
| Point-in-time size | Buckets from the SEC public-float frame at end of Q2 `FLOAT_YEAR` (2023), before `WINDOW_START` (2023-10-01). `fetch_frame(..., max_age=inf)` freezes it. No look-ahead in bucket assignment |
| Random sample | `sample_universe(sizes, seed=7)`: random CIKs per bucket, oversampled 2.5x because `company_events` drops non-operating entities, SIC 6770 (SPACs) and CIKs with no ticker |
| Events | Non-amended filings in `WINDOW_START..WINDOW_END` (2026-08-31) mapped by `pipeline.signals.signals_for_filing` (same taxonomy as live alerts), from `data.sec.gov/submissions` (older pages fetched when needed) |
| Acceptance-time day 0 | `day0_index()`: EDGAR acceptance time converted to ET. Before 15:30 ET -> that day's close; at/after 15:30 -> next trading day. `None` if no bar within 5 days (halts, gaps) |
| Reaction vs drift | `reaction` = day-0 close vs previous close (mostly not tradable). `drift_h` = day-0 close to day-h close (tradable). `HORIZONS = [5, 20]` |
| Market adjustment | Stock minus benchmark over the same dates (`BENCHMARK`: IWM, SPY for large). `bench_ret` requires exact date matches |
| Fixed direction | From the signal prior: `"-"` short, `"+"` and `"?"` long. Set before results |
| Costs | `COSTS` round trip per bucket (nano 3% ... large 0.1%) |
| Borrow | Shorts pay `BORROW_APR[bucket] * h / 252` (nano 50%/yr, micro 25%, small 5%...) |
| Baseline | `baseline_events()`: same companies at 10:00 ET every `BASELINE_STEP` (21) trading days, signal `"baseline"`. Results report `excess_vs_baseline` and Welch `t_vs_baseline` |
| Winsorizing | Reaction and each drift clipped at the 1st/99th percentile per bucket (`summarize`) |
| Min sample | Groups with fewer than `MIN_N` (20) events are not tested |
| Bonferroni | `t_crit` from 0.05 / (2 x number of tests) over every (signal, bucket, horizon) tested |

`significant` requires all of: `|t_stat| >= t_crit`, `|t_vs_baseline| >= t_crit`, mean and excess pointing
the prior's way (skipped for `"?"`), and `mean_net > 0`. `nominal_significant` is just `|t| >= 1.96`.

Known limits (also written into the output `caveats`): survivorship (delisted names lose ticker or prices;
see `coverage.no_ticker` / `no_prices`), flat borrow estimate, no beta/factor model, close fills assumed,
overlapping events overstate t, one sample period.

## prices.py

- `load_prices(ticker, start, end, cache_dir) -> PriceSeries | None`: Yahoo Finance chart API
  (`query1.finance.yahoo.com/v8/finance/chart`), daily adjusted closes (`adjclose`), split/dividend adjusted.
- **Personal research use only**: unofficial endpoint, terms restrict commercial use. Throttled
  (`_MIN_INTERVAL` 0.35 s), cached per `{ticker}_{start}_{end}.json` (404s cached too), never served by the
  API or redistributed. Swap to a licensed feed before anything public.
- Yahoo drops most delisted tickers -> survivorship bias. 429 -> retry up to 3 times after 30/60/120 s (`_RETRY_BACKOFF`), then `None` (not cached).
- `yahoo_symbol()` maps `BRK.B` -> `BRK-B`. `parse_chart` skips null/non-positive closes; bar dates come
  from the UTC timestamp.
- Price requests use a fixed browser-like User-Agent, not `SEC_USER_AGENT`.
- `PriceSeries.close` (adjusted) is the only field to compute returns from. `raw_close` (split-adjustment
  undone, i.e. the price that printed) and `dollar_volume` are being added for `app/backtest/` (price and
  liquidity filters); the event study doesn't use them.

## Run it and where results go

```bash
docker compose build api
docker compose run --rm api python -m app.research.eventstudy [--nano 150 --micro 250 --small 250 --large 100]
docker compose restart api        # lifespan -> load_study() picks up the new file
```

- Output: `{DATA_DIR}/event_study.json` (`RESULTS_FILE`), i.e. `/app/data` in the `apidata` volume.
  Caches in the same volume: `public_float_CY2023Q2I.json`, `submissions/{cik}.json`, `prices/`.
  Reruns are fast; delete the caches only if you mean to refetch.
- CLI flags exist only for nano, micro, small and large (0 skips a bucket); `mid` has costs/benchmark
  entries but is never sampled.
- The API serves it at `GET /api/research/event-study`; `load_study()` keeps 20-day rows as `Evidence`
  keyed by (signal, bucket). Field names in the JSON are consumed by `schemas.Evidence` and by
  `EventStudy`/`StudyResult` in `frontend/src/lib/api.ts`: rename nothing without updating both.
- Publish a run by copying the JSON to `docs/results/event_study_YYYY-MM-DD.json`
  (e.g. `docker compose cp api:/app/data/event_study.json docs/results/event_study_<date>.json` while the
  API runs) and update the results summary in `README.md`. See `docs/AGENTS.md`.

## Tests

`backend/tests/test_eventstudy.py` covers `day0_index` cut-off, market adjustment in `measure`,
`summarize` needing to beat the baseline, `signals_for_filing`, buckets/`parse_frame`, `parse_chart`.
Use synthetic `PriceSeries`; never hit SEC or Yahoo in tests.
