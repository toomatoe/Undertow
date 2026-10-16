# docs/: research and published results

Plain Markdown and JSON, no build step. Docs are evidence for decisions, so keep them factual,
dated and sourced. Research and education only; nothing here is financial advice.

## What each doc is

| Path | What | Owner / status |
|---|---|---|
| `FEASIBILITY.md` | Original feasibility report: what successful players exploit, strategies with evidence ranked for a solo builder, US rules (2026), free data/broker/news stack, v1 architecture, build order, sources | Stable background. Edit only to correct facts; add new findings elsewhere |
| `PRODUCT_RESEARCH.md` | Product research (market, users, positioning) | Being written by another agent now. Don't edit it concurrently |
| `results/event_study_YYYY-MM-DD.json` | Frozen copies of event-study runs, one file per run date. First: `event_study_2026-10-15.json` | Append-only; never edit a published file |
| `AGENTS.md` | This guide | |

The root `README.md` carries the human-readable summary of the latest results ("First results" section)
and the roadmap; `docs/results/` holds the raw evidence behind those numbers.

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
4. Update the "First results" / latest-results section of `README.md` from the JSON: numbers of events,
   companies, tests, and which results are `significant` vs nominal only. Quote `n`, `t`, `excess_vs_baseline`
   and `mean_net`, and keep the "lead, not a strategy" caveats (non-independent events, survivorship, borrow).
5. `docker compose restart api` so the Edge Lab and signal cards serve the new run.
6. If a result disappears or flips in a new run, say so in the README rather than silently replacing it.

## Rules

- No secrets, personal emails or `.env` contents in docs. Example SEC User-Agents use `example.com`.
- Price-derived numbers come from Yahoo (personal research use); publish summaries and statistics, never
  raw price series.
- Cite papers by author and year (as `FEASIBILITY.md` and `README.md` do).
