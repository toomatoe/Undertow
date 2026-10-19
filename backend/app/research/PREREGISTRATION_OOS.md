# Pre-registration: out-of-sample Edge Lab replication (2020-23, fresh companies)

- **Date registered:** 2026-10-19
- **Status:** registered before any out-of-sample result exists. No OOS run had been executed when this
  file was written and committed. Any later change to anything below is a new design and needs a new,
  dated pre-registration (see `AGENTS.md` in this folder: change the design before looking at results).
- **Implemented by:** `backend/app/research/oos.py` (`OOS_DESIGN`, `HYPOTHESES`, `T_CRIT_CONFIRMATORY`,
  `confirmatory()`). `backend/tests/test_oos.py` asserts the code matches the constants in this file.
- **In-sample reference:** `docs/results/event_study_2026-10-15.json` (window 2023-10-01 to 2026-08-31,
  frame CY2023Q2, seed 7, 102 tests).

Research and education only. Results are hypothetical, market-adjusted historical averages, not advice.

## 1. Question

Do the in-sample leads replicate on an earlier, non-overlapping period with companies the in-sample
study never looked at?

## 2. Sample

| Item | Fixed value |
|---|---|
| Event window | **2020-10-01 to 2023-08-31** (acceptance date, ET). Ends a month before the in-sample window starts, leaving room for 20 trading days of drift without overlap |
| Size frame | SEC public-float frame **CY2020Q2** (`FLOAT_YEAR` 2020), frozen (`max_age=inf`). Bucket cut-offs as in `pipeline.companies.BUCKETS` |
| Sample sizes | **nano 150 / micro 250 / small 250 / large 100** kept companies per bucket (`mid` not sampled) |
| Random seed | **2020** (same 2.5x oversample rule as in-sample) |
| Fresh companies | Exclude **every CIK in the in-sample candidate list**: `sample_universe({nano:150, micro:250, small:250, large:100}, float_year=2023, seed=7)`, i.e. including the 2.5x oversample, not just the companies that were kept |
| Design name | `oos_2020_2023` (written to `config.study`) |
| Output | `{DATA_DIR}/event_study_oos.json`. Never overwrites `event_study.json` (the live evidence) |

## 3. Unchanged from the in-sample design

Same signal taxonomy (`pipeline.signals`), acceptance-time day 0 (15:30 ET cut-off), horizons 5 and 20
trading days, market adjustment (IWM; SPY for large), round-trip costs per bucket, borrow APR for shorts,
ordinary-day baseline every 21 trading days, winsorizing at the 1st/99th percentile per bucket, `MIN_N` 20.

## 4. Confirmatory hypotheses (family of exactly 3)

All on the 20-trading-day market-adjusted drift, direction **"-"** (short: net = -mean - cost - borrow).

| Id | Signal code | Buckets | Horizon | Direction |
|---|---|---|---|---|
| **H1** | `offering_priced` (424B4/424B5) | nano | 20d | "-" |
| **H2** | `unregistered_equity` (8-K item 3.02, unregistered share sale; the "unregistered_sale" lead) | micro + nano, pooled | 20d | "-" |
| **H3** | `material_agreement` (8-K item 1.01) | nano | 20d | "-" |

H3 note: in-sample, `material_agreement` has a "?" prior and was measured long; its strong negative
drift was a lead. It is now pre-registered as a **short**.

Pooling (H2): events from both buckets are combined. Each event is winsorized with its own bucket's bounds
and pays its own bucket's cost and borrow; the baseline is the pooled baseline of the same buckets.

### Critical value

Bonferroni over the family of 3, two-sided alpha 0.05:
`t_crit = NormalDist().inv_cdf(1 - 0.05 / 6) = 2.394` (rounded **2.39**), i.e. 0.05/3 per hypothesis,
split over two tails; the same 0.05 / (2 x tests) rule the in-sample grid uses.

Note: the planning brief for this work quoted "about 2.64" next to this formula. That number is an arithmetic
slip (2.64 is the two-sided Bonferroni value for a family of 6). The formula and the family of 3 are what is
registered; the critical value is the formula's result, 2.394.

### Test statistics

- `t_clustered`: firm-clustered (CR1) t of the mean drift vs zero, clusters = companies (tickers):
  `se = sqrt(G/(G-1) * sum_g (sum_{i in g} (x_i - mean))^2) / n`.
- `t_vs_baseline_clustered`: (mean event drift - mean baseline drift) / sqrt(se_event^2 + se_baseline^2),
  each SE clustered by company. Event and baseline samples share companies, so this is an approximation
  (it ignores their covariance).

### Verdict rules (applied mechanically)

| Verdict | Rule |
|---|---|
| **underpowered** | n < 20 events **or** companies < 15. Checked first; no other rule applies |
| **replicated** | all of: n >= 20; companies >= 15; \|t_clustered\| >= t_crit; \|t_vs_baseline_clustered\| >= t_crit; mean drift < 0 and excess vs baseline < 0 (the registered way); mean_net > 0 |
| **not replicated** | enough data (n >= 20 and companies >= 15) but any replication condition fails |

All comparisons use the unrounded statistics (the JSON shows them rounded). "Companies" counts distinct
tickers, the same as `companies` in the results rows.

Outcome language for any write-up: "replicated", "not replicated" or "underpowered". Nothing else
(no "almost significant", no "trend").

## 5. Exploratory analysis

Everything else in the full grid (every signal x bucket x horizon with n >= 20, about 102 cells in-sample)
is **exploratory**. It is reported in `results[]` with the original full-grid Bonferroni (`testing.t_critical`)
and the original `significant` rule. An exploratory hit is a lead for a future pre-registered test, not a
confirmation. The H1-H3 cells also appear in `results[]`; their confirmatory verdict is only the one in the
`confirmatory` block.

## 6. Reproducibility

- Inputs: SEC submissions and the CY2020Q2 frame (public), Yahoo daily adjusted closes (personal research
  use only; cached locally, never committed or published).
- Each run writes a hash-only manifest to `{DATA_DIR}/snapshots/` (`inputs_manifest` in the results).
- `python -m app.research.oos --offline` replays from cache without network access and fails on cache misses
  unless `--allow-missing`.
