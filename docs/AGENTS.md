# docs/: research and published results

Plain Markdown and JSON, no build step. Docs are evidence for decisions, so keep them factual,
dated and sourced. Research and education only; nothing here is financial advice.
QuantDesk is local-only (decision 2026-10-19): no paid tier, accounts or hosting. Monetization research is background only.

## What each doc is

| Path | What | Owner / status |
|---|---|---|
| `FEASIBILITY.md` | Original feasibility report: what successful players exploit, strategies with evidence ranked for a solo builder, US rules (2026), free data/broker/news stack, v1 architecture, build order, sources | Stable background. Edit only to correct facts; add new findings elsewhere |
| `PRODUCT_RESEARCH.md` | Product research (market, competitors, pricing, legal, distribution) | Background only: starts with the dated "Decision 2026-10-19: local-only, no paid tier" note. Keep the research body; don't turn it back into a plan |
| `results/event_study_YYYY-MM-DD.json` | Frozen copies of event-study runs, one file per run date. First: `event_study_2026-10-15.json` | Append-only; never edit a published file |
| `results/backtest_YYYY-MM-DD.json` | Frozen copies of backtest reports (`report_latest.json`). First: `backtest_2026-10-16.json` | Append-only |
| `results/event_study_oos_YYYY-MM-DD.json`, `results/event_study_insider_purchases_YYYY-MM-DD.json` | Frozen copies of the pre-registered out-of-sample and insider studies (`{DATA_DIR}/event_study_oos.json`, `{DATA_DIR}/event_study_insider_purchases.json`). Published: `event_study_oos_2026-10-19.json`, `event_study_insider_purchases_2026-10-19.json` | Append-only, same rules |
| `paper/WORKING_PAPER.md` | Working paper on all three studies and the backtest. Every headline number is listed in `HEADLINE` in `backend/app/research/paper_numbers.py` and checked against `results/` by `backend/tests/test_paper_numbers.py`. A byte-identical copy lives at `frontend/src/content/working-paper.md` (rendered at `/research/paper`) | Change a number -> update `HEADLINE` and the frontend copy in the same change |
| `plans/YYYY-MM-DD-*.json` | Batch plans from the planning step (work items, owned paths, acceptance). `2026-10-19-batch.json` (platform + studies), `2026-10-19-v1-local.json` (v1.0 local-only batch) | Historical record; don't edit after the batch runs |
| `agent-graph.json` | Machine-readable module graph: paths (every repo file in exactly one module), AGENTS.md, depends_on, tests, hotspots, shared resources | Update when a module or top-level file is added |
| `AGENT_PROCESS.md` | Multi-agent process: Plan, ownership waves, Build, 2-lens Review, exclusive Verify, final Docs item, Critic | Update when `.claude/workflows/feature-graph.js` changes |
| `AGENTS.md` | This guide | |

The root `README.md` carries the human-readable status, a "Key findings" summary copied from the working paper (all
hypothetical figures labelled) and a short "What's next (research)" list; `docs/results/` holds the raw evidence behind
those numbers and `docs/paper/` the full write-up.

## Results JSON format

Written by `backend/app/research/eventstudy.py` (`run()`), unchanged when copied here:
- `generated_at`, `config` (window, `size_measured`, `sample_sizes`, `horizons`, `min_n`,
  `costs_round_trip`, `borrow_apr_for_shorts`, `baseline_step_days`, `benchmark`, `price_source`)
- `coverage` per bucket (`companies`, `with_prices`, `no_prices`, `no_ticker`, `events`, `measured_events`,
  `baseline_obs`, ...), `measured_events`
- `testing` (`n_tests`, `t_critical`, `baseline` per bucket with `mean_5`/`mean_20`)
- `results[]` per (signal, bucket, horizon): `n`, `companies`, `mean_reaction`, `mean_abnormal`,
  `median_abnormal`, `t_stat`, `hit_rate`, `cost`, `borrow`, `mean_net`, `baseline_mean`,
  `excess_vs_baseline`, `t_vs_baseline`, `significant`, `nominal_significant`
- `caveats[]`
- Added 2026-10-19 (absent from `event_study_2026-10-15.json`): `config.study` (design name), `config.design`,
  `inputs_manifest`, per row `t_stat_clustered`, `t_vs_baseline_clustered`, `clusters`, and a 7th caveat (clustered
  t-stats are reporting only). The OOS file adds `confirmatory`, `confirmatory_testing`, `preregistration`; the insider
  file adds `data_quality`, `preregistration`, `preregistered_on`, `opportunistic_vs_routine`, `testing.significance_rule`.
  `python -m app.research.snapshot compare --ignore-added OLD NEW` compares old and new files despite the additions.

The frontend's `EventStudy` type (`frontend/src/lib/api.ts`) reads the same shape, so an old results file
can be compared against a new one field by field.

## How to update results

1. Decide and document any design change in the `eventstudy.py` docstring **before** running
   (see `backend/app/research/AGENTS.md`: change the design before looking at results, never after).
2. Run in the container:
   `docker compose build api && docker compose run --rm api python -m app.research.eventstudy`
   (writes `/app/data/event_study.json` in the `apidata` volume).
3. Copy it out with a dated name, e.g. with the API running:
   `docker compose cp api:/app/data/event_study.json docs/results/event_study_<YYYY-MM-DD>.json`.
   Never overwrite an earlier file; a rerun on the same day gets a suffix.
4. Update the working paper (`paper/WORKING_PAPER.md`), `HEADLINE` in `paper_numbers.py` and the frontend copy, run
   `bash scripts/pytest.sh tests/test_paper_numbers.py`, then copy the changed numbers into the "Key findings" section
   of `README.md` exactly as the paper writes them. Keep `n`, `t`, `excess_vs_baseline`, `mean_net` and the caveats
   (non-independent events, survivorship, borrow), and label every net or simulated figure hypothetical.
5. `docker compose restart api` so the Edge Lab and signal cards serve the new run.
6. If a result disappears or flips in a new run, say so in the README rather than silently replacing it.

## Rules

- No secrets, personal emails or `.env` contents in docs. Example SEC User-Agents use `example.com`.
- Price-derived numbers come from Yahoo (personal, local research use); publish summaries and statistics, never
  raw price series. No public deployment with Yahoo data; public use would need a licensed feed.
- Cite papers by author and year (as `FEASIBILITY.md` and `README.md` do).
