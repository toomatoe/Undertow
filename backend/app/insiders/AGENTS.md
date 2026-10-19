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
The live forward test (below) uses `FORWARD_TEST_SIGNALS` in signals.py, which is outside `ALL_SIGNALS`.

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

## Live forward test of the cluster finding (`live.py`, `settings.py`, `evidence.py`)

Forward-tests the one cell that was significant under the pre-registered rule: `insider_cluster_purchase`,
**micro**, **5 trading days** (excess vs baseline +1.66%, n=662, 177 companies, clustered t 3.29; in-sample,
hypothetical). Nothing else from this study goes live, and no new hypothesis is tested.

`live.poll_form4(settings, universe, session_factory, *, http_get=httpx.get, now=None)`, called from
`pipeline.ingest.poll_edgar` (same `EDGAR_POLL_SECONDS` cadence and `_edgar_lock`, in its own try/except via
`ingest._poll_form4`, so a Form 4 failure never breaks the 8-K poll; with `EDGAR_POLL_SECONDS=0` it runs in
`run_ingest` instead). One cycle:

1. EDGAR `getcurrent` for `type=4` (`owner=include`, `count=100`, Atom), `User-Agent: settings.sec_user_agent`.
   `parse_feed()` keeps `"4 - Company (CIK) (Issuer)"` entries (drops `4/A` and the reporting-owner rows),
   filing date from the entry's `Filed:` field.
2. Only issuers with `Company.size_bucket == "micro"`. **Deviation (necessary):** the live test uses today's
   bucket (latest SEC public float, `pipeline.companies`), not the study's frozen CY2023Q2 frame.
3. At most `MAX_XML_PER_CYCLE` (25) new accessions per cycle: `{cik}/{acc}/index.json` -> first `.xml` ->
   `form4.raw_xml_url()` -> `parse_ownership_xml()` (DOCTYPE/ENTITY rejected; counted, never refetched).
   Accession seen-set (and the emitted issuer-days) in `{DATA_DIR}/insider_live_seen.json` (last 20,000 kept).
   A transient HTTP error leaves the accession unseen so the next cycle retries it.
4. **Shared rules, not a fork:** `rows_from_xml()` turns the parsed dict into `datasets.TransactionRow`s, then
   `study.is_qualifying` / `study.exclusion_reason` (Form 4, P/A, shares and price > 0, director or officer,
   not 10b5-1) and `study.insider_cik` (lowest director/officer CIK) decide. Qualifying filings are appended to
   `{DATA_DIR}/insider_live_purchases.jsonl` (`accession, issuer_cik, ticker, insider_cik, filing_date, value,
   accepted_at`; one line per filing). No DB schema change.
5. Each issuer-day of the last `REEVALUATE_DAYS` (3) not yet emitted goes through `study.build_events()` on the
   stored purchases: same `MIN_VALUE` ($10,000 issuer-day total) and `CLUSTER_DAYS` window `[d-10, d]`, purchases
   of any size counting toward the cluster. A `CLUSTER` event becomes one Article via
   `pipeline.ingest.store_and_publish` (SSE `article` + `NEW_ARTICLE_HOOKS`): source `edgar`, form `4`,
   signals `["insider_cluster_purchase"]` (severity 2, `pipeline.signals.FORWARD_TEST_SIGNALS`), ticker tagged
   (`edgar`), url = EDGAR filing index of the day's last filing, `body=""` (no filing-text fetch), headline
   `Insider cluster purchase: TICK (n insiders, $X total)` (n = distinct insiders in the window, X = the
   issuer-day total), published_at = SEC acceptance time.

Every SEC request goes through `datasets.throttle()` (<= 8/s); worst case per cycle is 1 + 2 x 25 requests.
Gated on `EDGAR_ENABLED` and `INSIDER_LIVE_ENABLED` (default true; `settings.InsiderLiveSettings`, delivery
pattern, should move into `app.config.Settings` later).

**Warm-up:** the purchase store starts empty, so a cluster whose earlier buyer filed before the first start is
missed. Clusters are fully observable about 10 calendar days after the first start (and after any outage).

**Day-0 note:** the study measures drift from the first close after the filing date (event timed 23:59 ET).
The journal enters at day 0 + 1 from the SEC acceptance time (`ENTRY_DELAY` 1, like every journal row): for a
filing accepted before the close that is the same close as the study's start; for an after-close filing it is
one trading day later. The journal rule is the live one; keep this in mind when comparing the two.

**Evidence** (`evidence.load_forward_test_row`): the micro / 5-day `insider_cluster_purchase` row of
`{DATA_DIR}/event_study_insider_purchases.json` when present, else `forward_test_evidence.json` (a verbatim
copy of that row from `docs/results/event_study_insider_purchases_2026-10-19.json`; do not edit it;
`test_bundled_row_matches_docs_results` compares it with docs/results when `/repo` is mounted). `main.to_out`
attaches it as `EvidenceOut` with `study="insider_purchases"`, `forward_test=true`, `t_stat_clustered`,
`companies` (loaded at startup; restart the API after a new insider study run). The journal judges these rows as a
hypothetical long at 5 days (`journal.service.EVALUATION_HORIZONS`) and labels them
"forward test of pre-registered finding".

The main taxonomy is untouched: `insider_cluster_purchase` lives only in `FORWARD_TEST_SIGNALS`; resolve stored
codes with `pipeline.signals.signal_def()`, never `ALL_SIGNALS[code]`.

## Tests

`backend/tests/test_insiders.py` (fixtures in `backend/tests/fixtures/form4/`: two hand-made Form 4 XMLs
and `2024q1_form345.zip`, regenerated by `make_quarter_zip.py`, which documents every scenario). Covers
parsing, DOCTYPE/ENTITY rejection, `raw_xml_url`, the join and schema drift, every filter, aggregation,
clusters, day 0, CMP edge cases, the pre-registration constants and an offline end-to-end run with stub
prices (schema-compatible output, `Evidence` rows, cross-check, determinism, CLI guard). No network.

`backend/tests/test_insider_live.py` (fixtures in `backend/tests/fixtures/form4_live/`: a canned getcurrent Atom
feed and Form 4 XMLs for a director, an officer, two small buyers, a 10b5-1 plan, a code-S sale, a 10%-owner-only
filing, a non-micro issuer and a DOCTYPE document; HTTP client and throttle monkeypatched). Covers feed parsing,
the shared rules, single purchase vs cluster (emits once), the 10/11-day window edge, small purchases counting
toward the cluster but not the $10,000 minimum, exclusions, DOCTYPE, seen-set, per-cycle cap, retry, gates,
isolation from the 8-K poll, bundled evidence vs docs/results, `to_out` evidence, the journal row (long, 5d,
label) inside a sealed and verified day, and the alerts hook not raising.
