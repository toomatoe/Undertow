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
overlapping events overstate t, one sample period, clustered t-stats are reporting only.

## StudyDesign API (stable: the OOS and insider studies build on it)

- `StudyDesign(name, window_start, window_end, float_year, seed, sizes, exclude_ciks, results_file)`
  (frozen). `in_sample_design(sizes)` is the original design (`"in_sample"`, seed 7, CY2023Q2);
  `run(sizes)` = `run_design(in_sample_design(sizes))`, output unchanged apart from additive fields.
- `run_design(design, event_source=None, signal_defs=None, *, offline=False, data_dir=None, user_agent=None)`
  = `collect()` (sample, events, prices, measure -> `(measurements, coverage)`) + `build_study()`.
  `event_source(cik, bucket, user_agent, cache_dir, *, window, offline) -> (ticker, events, status)`,
  default `company_events`; status `"ok"` keeps the company.
- `sample_universe(sizes, data_dir, ua, seed, *, float_year, exclude_ciks, offline)`: excluded CIKs are
  removed before sampling; deterministic per seed.
- `summarize(measurements, signal_defs=ALL_SIGNALS)`: pass your own `{code: SignalDef}` map for a new
  taxonomy. `winsor_bounds()` is the per-bucket clipping it uses.
- Output additions: `config.study` (design name), `config.design` (`to_config()`; `exclude_ciks` is
  summarized as count + sha256), `inputs_manifest`, and per results row `t_stat_clustered`,
  `t_vs_baseline_clustered`, `clusters` (= `companies`).

## Firm-clustered t-stats (reporting only in-sample)

- `clustered_t(values, clusters)`: CR1, `se = sqrt(G/(G-1) * sum_g (sum_{i in g}(x_i - mean))^2) / n`,
  0 when G < 2. Equals the plain t when every event is its own cluster.
- `clustered_welch_t(a, ca, b, cb)`: mean difference over `sqrt(se_a^2 + se_b^2)` from clustered SEs.
  Approximation: event and baseline samples share companies and their covariance is ignored.
- Clusters are tickers. In-sample `significant` still uses the plain `t_stat` / Welch `t_vs_baseline`;
  only the OOS confirmatory test uses the clustered versions.

## Offline replay and manifests (`snapshot.py`)

- `--offline` on `python -m app.research.eventstudy` and `app.research.oos`: `get_json(..., offline=True)`
  and `load_prices(..., offline=True)` never touch the network. A cache miss returns None, is recorded
  (`snapshot.record_miss`), counted per bucket as `coverage[bucket]["offline_miss"]` and listed at the end;
  the run exits non-zero unless `--allow-missing` (then `offline_misses` is added to the output).
  `--output PATH` writes elsewhere (the replay scripts use `{DATA_DIR}/snapshots/replay_*.json`).
- 404s from `get_json` are cached as `null`, and older submissions pages are cached under
  `submissions/pages/`, so later replays can read them. Runs made before 2026-10-19 did not cache those
  pages, so replaying such a run may report misses for companies with very long filing histories.
- Each CLI run writes a hash-only manifest to `{DATA_DIR}/snapshots/<study>_<UTC>.json`: SHA-256 of every
  cache file read (registry in `snapshot.py`, active only while a study CLI runs), the frame file, `GIT_SHA`
  (or `unknown`) and the sha256 of the canonical results (sort_keys, without `generated_at`, timing fields
  and `inputs_manifest`). No cached content goes into it; cached Yahoo data is never committed or published.
- `python -m app.research.snapshot write [--study PATH]` (hashes all cache files when there is no registry:
  `*.json`, `*.zip` and `*.xml` under `CACHE_SUBDIRS` = `submissions/`, `prices/`, `insider_datasets/`, `insider_xml/`,
  plus `public_float_*`; keep the insider names in sync with `insiders.datasets.CACHE_SUBDIR` / `insiders.study.XML_CACHE_SUBDIR`),
  `verify MANIFEST` (exit 1 on a changed/missing input or results file), `compare A B [--ignore-added]`
  (prints `IDENTICAL` or `DIFF` with key paths; rows keyed `signal/bucket/horizon`; `-` reads stdin).
- `make reproduce` / `scripts/reproduce.sh main` replays the in-sample study offline in the api image and
  compares it with the newest `docs/results/event_study_*.json` (`--ignore-added`, since published files
  predate the additive fields). `--ignore-added` skips keys only in B and items appended to the end of a
  list in B whose leading items match A (the clustered-t caveat is the 7th caveat after the published 6). `make reproduce-oos` / `make reproduce-insiders`
  (`scripts/reproduce.sh oos|insiders`) replay the OOS / Form 4 insider study offline to `snapshots/replay_*.json` and
  compare it with the online run's `event_study_oos.json` / `event_study_insider_purchases.json` when one exists
  (`--ignore-added`, because an offline replay adds `offline_misses`).

## Out-of-sample study (`oos.py`)

Pre-registered in [PREREGISTRATION_OOS.md](PREREGISTRATION_OOS.md) (2026-10-19): window 2020-10-01..2023-08-31,
frame CY2020Q2, seed 2020, same sample sizes, excluding every in-sample candidate CIK (`EXCLUDE_FROM`,
oversample included). `OOS_DESIGN` + `HYPOTHESES` (H1 `offering_priced` nano, H2 `unregistered_equity`
micro+nano pooled, H3 `material_agreement` nano; all 20d, short) + `T_CRIT_CONFIRMATORY`
(Bonferroni family of 3: `inv_cdf(1 - 0.05/6)` = 2.394). `confirmatory(measurements)` returns
`replicated` / `not replicated` / `underpowered` (n < 20 or companies < 15) per hypothesis.
`python -m app.research.oos [--offline]` writes `{DATA_DIR}/event_study_oos.json` (same schema plus
`confirmatory`, `confirmatory_testing`, `preregistration`) and refuses to write `event_study.json`.
`results[]` there is exploratory. Changing any OOS constant needs a new dated pre-registration first.
Research jobs can launch it as kind `event_study_oos`; only `event_study` reloads the live evidence.

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

## Working paper numbers (`paper_numbers.py`)

`docs/paper/WORKING_PAPER.md` writes up all three studies and the backtest. Every headline number it quotes is
listed in `HEADLINE` (label, result file, selector, field, value, tolerance, `fmt`). Selectors: a `results` row
by `{signal, bucket, horizon_days}`, a row of another list (`{"list": "confirmatory", "hypothesis": "H1"}`) or a
dotted path with `[i]` indices (`{"path": "periods.A.waterfall[0]"}`). `check(repo_root)` returns mismatches:
the JSON value must equal `value` within `tolerance`, and `fmt.format(value)` (e.g. `"+1.66%"`, `"t = 3.29"`,
`"n = 662"`) must appear literally in the paper. `find_repo_root()`: env `UNDERTOW_REPO_ROOT`, else `/repo`
(when it has `docs/`), else `Path(__file__).parents[3]` (CI checkout). Pure stdlib; CLI:
`python -m app.research.paper_numbers`.

**Rule: change a number in the paper -> update HEADLINE** (and a republished result file -> update both).
Then copy the paper to `frontend/src/content/working-paper.md` (byte-identical; the frontend build context cannot
see `docs/`), which `/research/paper` renders.

`backend/tests/test_paper_numbers.py` asserts `check()` is empty, `HEADLINE` covers all four result files with at
least 12 claims, the frontend copy equals the paper (CRLF-normalized), and that `check()` catches paper and JSON
drift. It needs the repo root: `scripts/pytest.sh` mounts it read-only at `/repo`; it skips only when `docs/` is
missing (bare api image).

## Tests

`backend/tests/test_eventstudy.py` covers `day0_index` cut-off, market adjustment in `measure`,
`summarize` needing to beat the baseline, `signals_for_filing`, buckets/`parse_frame`, `parse_chart`,
`run()` matching a golden hash of the pre-refactor output (minus additive fields), `run_design` with a stub
`event_source`, clustered t-stats, `sample_universe` exclusion/determinism, and offline mode with httpx
patched to raise. `test_oos.py` asserts `OOS_DESIGN` matches the pre-registration and checks the verdicts;
`test_snapshot.py` covers manifest round-trip/tamper detection, `compare_results` and that `CACHE_SUBDIRS` includes
(and the CLI `write` hashes) the insider caches.
Use synthetic `PriceSeries`; never hit SEC or Yahoo in tests.
