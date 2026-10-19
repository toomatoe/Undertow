# Pre-registration: Form 4 insider-purchase event study (small caps, 2023Q4-2026Q2)

- **Date registered:** 2026-10-19
- **Status:** registered before any result exists. The study had never been run (on real data) when
  this file was written. Any later change to anything below is a new design and needs a new, dated
  pre-registration (see `backend/app/research/AGENTS.md`: change the design before looking at results).
- **Implemented by:** `backend/app/insiders/` (`study.py`: `DESIGN`, `SIGNAL_DEFS`, `EVENT_START`,
  `EVENT_END`, `HISTORY_QUARTERS`, `MIN_VALUE`, `CLUSTER_DAYS`, `CROSSCHECK_N`; `classify.py`: CMP rule;
  `datasets.py`: loader and filters' inputs; `form4.py`: raw XML parser for the cross-check).
  `backend/tests/test_insiders.py` asserts the code matches the constants in this file.
- **Relation to the main study:** separate study with its own signal taxonomy and its own Bonferroni
  family. Nothing is added to `app/pipeline/signals.py`, so the main study's test count is unchanged.

Research and education only. Results are hypothetical, market-adjusted historical averages, not advice.

## 1. Question

After a director or officer of a US small company discloses an open-market purchase of the company's
stock on Form 4, does the stock drift vs the index over the next 5 and 20 trading days, after costs and
compared with ordinary days? Following Cohen, Malloy & Pomorski (2012), is the drift larger for
"opportunistic" insiders than for "routine" ones?

## 2. Data

| Item | Fixed value |
|---|---|
| Insider data | SEC **Insider Transactions Data Sets** (quarterly flattened Form 3/4/5 tables, https://www.sec.gov/dera/data/form-345), files `{year}q{q}_form345.zip`. Tables used: `SUBMISSION`, `REPORTINGOWNER`, `NONDERIV_TRANS`, joined on `ACCESSION_NUMBER` |
| Insider history quarters | **2020Q1 to 2026Q2** (classification look-back) |
| Event quarters | Filing date **2023-10-01 to 2026-06-30** (2023Q4 to 2026Q2, the latest complete quarter). Filings dated after 2026-06-30 are excluded |
| Raw XML (cross-check only) | The Form 4 XML in the EDGAR archive, located via `data.sec.gov/submissions` `primaryDocument` |
| Prices | Yahoo Finance daily adjusted closes (personal research use only; never published, only aggregate statistics are) |
| SEC fair access | `SEC_USER_AGENT` from settings, at most 8 requests per second |

## 3. Universe

| Item | Fixed value |
|---|---|
| Size frame | SEC public-float frame **CY2023Q2** (`float_year` 2023), frozen; buckets as `pipeline.companies.bucket_for` |
| Companies | Operating companies (submissions `entityType == "operating"`), not SIC 6770 (SPACs), with at least one ticker (first ticker used for prices) |
| Random caps per bucket | **nano 300, micro 400, small 400, large 100** (large is a control) kept companies |
| Seed | **11**, with the shared `sample_universe` rule (2.5x oversample, kept until the cap is reached) |
| Design name | `insider_purchases` (written to `config.study`) |
| Output | `{DATA_DIR}/event_study_insider_purchases.json`, same schema as `event_study.json` |

Companies in the sample with no insider events still contribute ordinary-day baseline observations.

## 4. Events

A **qualifying purchase** is one `NONDERIV_TRANS` row with all of:

1. `SUBMISSION.DOCUMENT_TYPE == "4"` (amendments `4/A`, and Forms 3 and 5, excluded);
2. `TRANS_CODE == "P"` (open-market or private purchase) and `TRANS_ACQUIRED_DISP_CD == "A"`;
3. `TRANS_SHARES > 0` and `TRANS_PRICEPERSHARE > 0` (prices above 1e6 are treated as missing);
4. at least one reporting owner on the filing is a **director or officer** (`RPTOWNER_RELATIONSHIP`
   contains Director or Officer). Filings whose owners are only 10% owners (or "other") are excluded;
5. the filing is not flagged `AFF10B5ONE` (Rule 10b5-1 plan box) when that column is present
   (values `1`, `true`, `y`, `yes`, `x`, case-insensitive, count as flagged).

The **insider** of a qualifying purchase is the lowest CIK among the filing's director/officer owners
(one insider per filing, so joint filings are not double counted). Its value is shares x price.

**Aggregation:** qualifying purchases are grouped per issuer (`ISSUERCIK`) per filing date. A group is an
event only if its total value is at least **$10,000** (`MIN_VALUE`). Only groups with a filing date in the
event quarters are events (earlier purchases still count toward the cluster look-back below).

**Day 0:** the datasets carry `FILING_DATE` but no acceptance time, so day 0 is conservatively the first
close **after** the filing date (the next trading day; the event is timed 23:59 ET on the filing date and
the shared `day0_index` rule moves it to the next bar). The filing date itself is never day 0.

## 5. Signals (all direction "+", long only)

| Code | Definition |
|---|---|
| `insider_purchase` | Every event (all qualifying purchases of the issuer-day, total >= $10,000) |
| `insider_cluster_purchase` | An event on filing date d where at least **2 distinct insiders** filed qualifying purchases at the issuer within the 10 calendar days `[d - 10, d]` (`CLUSTER_DAYS`), counting purchases of any size, i.e. d brings the second or a later distinct buyer of a cluster |
| `insider_purchase_opportunistic` | The issuer-day's qualifying purchases by insiders classified **opportunistic**; event if their total >= $10,000 |
| `insider_purchase_routine` | Same for insiders classified **routine** (control) |

**CMP classification** (`classify.py`), per insider CIK and per purchase, for the calendar year Y of the
purchase's transaction date:

- History = the insider's trades (`TRANS_CODE` P or S, Form 4 or 5, not amended, any issuer, any role)
  with a transaction date in years Y-3, Y-2, Y-1 and a filing date on or before the event's filing date
  (point in time).
- **Unclassified** unless the insider has at least one trade in **each** of the 3 prior years. Unclassified
  insiders are excluded from both the opportunistic and the routine signal.
- **Routine** if there is a calendar month in which the insider traded in each of the 3 prior years;
  **opportunistic** otherwise.

## 6. Tests and cost model

Unchanged from the main study: horizons **5 and 20** trading days, market adjustment (IWM; SPY for large),
round-trip `COSTS` per bucket, ordinary-day baseline every 21 trading days in the same window, winsorizing at
the 1st/99th percentile per bucket, `MIN_N` 20. Long only, so no borrow.

**Significance** (written to each row's `significant`): Bonferroni across this study's tested cells
(every signal x bucket x horizon with n >= 20): `t_crit = NormalDist().inv_cdf(1 - 0.05 / (2 x n_tests))`.
A cell is significant only if all of:

- `|t_stat_clustered| >= t_crit` (firm-clustered CR1 t vs zero from `eventstudy.clustered_t`, clusters = companies);
- `|t_vs_baseline| >= t_crit` (the main study's vs-baseline requirement, Welch t);
- mean abnormal drift > 0 and excess vs baseline > 0 (the "+" prior);
- `mean_net > 0` (after the bucket's round-trip cost).

The main study's unclustered verdict is kept per row as `significant_unclustered` (reporting only).

**Pre-registered expectation:** opportunistic > routine. Reported descriptively per bucket and horizon in
`opportunistic_vs_routine` (difference of mean abnormal drift); it is not a separate significance test.

## 7. Data quality

Cross-check a random **50** events (`CROSSCHECK_N`, seed 11, drawn from the `insider_purchase` events of
the kept companies): for one random qualifying filing of each event, every qualifying dataset row must match
a `nonDerivativeTransaction` of the raw Form 4 XML (parsed by `form4.py`) on code, transaction date,
shares (within 0.5 shares or 0.1%) and price (within $0.01 or 0.1%). The output reports
`data_quality.xml_crosscheck_n` (events whose XML could be read), `match_rate` (share of those events that
fully match) and the number of unavailable documents.

## 8. Reproducibility

- Inputs: SEC datasets, submissions and Form 4 XML (public; cached under `{DATA_DIR}/insider_datasets/`,
  `submissions/`, `insider_xml/`), Yahoo prices (cached, never committed).
- Each run writes a hash-only manifest to `{DATA_DIR}/snapshots/` (`inputs_manifest` in the results).
- `python -m app.insiders.study --offline` replays from cache without network access and fails on cache
  misses unless `--allow-missing`. `--quarters` narrows the loaded quarters for debugging only; a run with
  it is recorded as `config.quarters_override` and is not the registered study.
