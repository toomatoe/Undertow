# backend/app/insiders/: Form 4 insider-purchase event study

Question: after a director or officer of a small company reports an open-market purchase on Form 4,
does the stock drift vs the index over 5 and 20 trading days, after costs and vs ordinary days? Is the
drift larger for "opportunistic" than for "routine" insiders (Cohen, Malloy & Pomorski 2012)?

**Pre-registered in [PREREGISTRATION.md](PREREGISTRATION.md) (2026-10-19) before any result existed.**
The research rule applies in full (see `backend/app/research/AGENTS.md`): any change to the universe,
filters, day-0 rule, signals, CMP rule or significance rule needs a new dated pre-registration first.
`tests/test_insiders.py::test_constants_match_preregistration` ties the code constants to that file.

This is a **separate study**. Never add the insider signals to `app/pipeline/signals.py`: that would
change the main study's taxonomy and its Bonferroni count. `test_main_signal_taxonomy_untouched` guards it.

## Data and licensing

| Input | Source | Terms |
|---|---|---|
| Insider rows | SEC Insider Transactions Data Sets (`{year}q{q}_form345.zip`, https://www.sec.gov/dera/data/form-345); `SUBMISSION`, `REPORTINGOWNER`, `NONDERIV_TRANS` | Public SEC data |
| Raw Form 4 XML | EDGAR archive, located via `data.sec.gov/submissions` `primaryDocument` (cross-check only) | Public SEC data |
| Company check | `data.sec.gov/submissions/CIK##########.json` (same cache as the main study) | Public SEC data |
| Prices | Yahoo chart API via `research.prices` | **Personal research use only**: only aggregate statistics are published, never prices |

SEC requests send `SEC_USER_AGENT` from settings and stay at or below 8/s (`datasets.throttle()`,
`MIN_INTERVAL` 0.125 s; `eventstudy.collect` sleeps 0.12 s per company). Caches under `DATA_DIR`:
`insider_datasets/` (zips), `submissions/` (shared), `insider_xml/{accession}.xml`, `prices/` (shared).
All four are in `research.snapshot.CACHE_SUBDIRS`, so `python -m app.research.snapshot write` hashes them too; if you
rename `datasets.CACHE_SUBDIR` or `study.XML_CACHE_SUBDIR`, update that tuple (`test_snapshot.py` checks it).

## Modules

- **form4.py**: `parse_ownership_xml(xml_bytes)` (stdlib `xml.etree` only, no new dependency) -> dict with
  `document_type`, `period`, `aff10b5one`, `issuer {cik, ticker, name}`, `reporting_owners [{cik, name,
  is_director, is_officer, officer_title, is_ten_percent}]` and every `nonDerivativeTransaction`
  `{security_title, date, code, acquired_disposed, shares, price, shares_after, direct_indirect}`.
  Rejects any DOCTYPE/ENTITY declaration (`UnsafeXMLError`) before parsing; strips namespaces; tolerates
  empty `<value/>` and `<footnoteId/>`; prices <= 0 or > 1e6 become None. `raw_xml_url(cik, accession,
  primary_document)` strips the `xslF345X0n/` prefix from submissions' `primaryDocument`.
- **datasets.py**: `download_quarter(year, q, data_dir, user_agent, offline=)` caches the zip (offline: cache
  only, misses recorded via `snapshot.record_miss`). `iter_quarter(path, codes=)` / `load_quarter` stream
  the TSVs with `csv` (no pandas), join on `ACCESSION_NUMBER` into frozen `TransactionRow`s (owners sorted
  by CIK, typed dates/floats, `aff10b5one` None when the column is absent). Headers are checked against
  `REQUIRED_COLUMNS` (from the SEC readme) on every read; drift raises `SchemaError` naming the columns.
  Dates are `DD-MON-YYYY`. `AFF10B5ONE` is optional (2023+ quarters only).
- **classify.py**: `classify_trades(trade_dates, year)` -> `"routine"` / `"opportunistic"` / None per CMP
  (a trade in each of the 3 prior calendar years, routine if one month repeats in all 3).
  `TradeHistory` answers it point in time (only trades filed on or before the event's filing date).
- **study.py**: constants (`DESIGN` = StudyDesign `insider_purchases`, frame CY2023Q2, seed 11, caps nano 300 /
  micro 400 / small 400 / large 100, window 2023-10-01..2026-06-30), `SIGNAL_DEFS` (4 codes, all `"+"`),
  `load_insider_data()` (pass 1: qualifying purchases from 2023Q3..2026Q2; pass 2: P/S history 2020Q1..2026Q2
  of those insiders only, to bound memory), `build_events()` (per issuer per filing date, >= $10,000;
  cluster = 2+ distinct insiders in `[d-10, d]`; opportunistic/routine subsets), `make_event_source()`
  (company check like `company_events`, events timed 23:59 ET so day 0 = next trading day),
  `apply_significance()` (pre-registered rule: clustered t + Welch t vs baseline, `significant_unclustered`
  kept), `opportunistic_vs_routine()` (descriptive), `crosscheck()` (50 random events vs raw XML).

## Pipeline

```
download_quarter x 26 -> load_insider_data (2 passes) -> build_events -> run_design(DESIGN, event_source, SIGNAL_DEFS)
  -> apply_significance -> opportunistic_vs_routine -> crosscheck -> write_study (results + hash manifest)
```

Output `{DATA_DIR}/event_study_insider_purchases.json`: the `event_study.json` schema (`config.study` =
`insider_purchases`, `results[]` rows the Lab and `schemas.Evidence` read unchanged) plus `data_quality`
(`xml_crosscheck_n`, `match_rate`, `unavailable`, `mismatched_accessions`, `datasets` counters per filter),
`preregistration`, `preregistered_on`, `opportunistic_vs_routine`, `testing.significance_rule`. The CLI
refuses to write `event_study.json` (the live evidence).

```bash
docker compose run --rm api python -m app.insiders.study                     # ~1-2 h first run, cached after
docker compose run --rm api python -m app.insiders.study --offline           # replay from cache, fails on misses
docker compose run --rm api python -m app.insiders.study --offline --allow-missing --quarters 2024q1 2024q2  # debug only
make reproduce-insiders   # scripts/reproduce.sh insiders: offline replay to snapshots/replay_*.json, compared with the online run
```

`--quarters` is for debugging: it is recorded as `config.quarters_override` and is not the registered study.

## Future live "insider purchase" alert (not built)

A live alert would reuse `form4.py` unchanged: watch the EDGAR Form 4 feed (the alerts module's poller),
take each filing's `primaryDocument`, fetch `raw_xml_url(...)`, `parse_ownership_xml()`, then apply the same
filters as `study.exclusion_reason` (P/A, price > 0, director/officer, not 10b5-1) and the $10,000 minimum.
It would need its own signal code outside `pipeline/signals.py`'s main-study taxonomy, or a new
pre-registered decision to add it there, and its evidence line would come from this study's JSON.

## Tests

`backend/tests/test_insiders.py` (fixtures in `backend/tests/fixtures/form4/`: two hand-made Form 4 XMLs
and `2024q1_form345.zip`, regenerated by `make_quarter_zip.py`, which documents every scenario). Covers
parsing, DOCTYPE/ENTITY rejection, `raw_xml_url`, the join and schema drift, every filter, aggregation,
clusters, day 0, CMP edge cases, the pre-registration constants and an offline end-to-end run with stub
prices (schema-compatible output, `Evidence` rows, cross-check, determinism, CLI guard). No network.
