# Undertow/ (machine-generated): guide for agents and humans

This folder is written by Undertow, a locally run research tool for small-cap SEC filings. It is regenerated every
few minutes. Research and education only: every number here is historical or hypothetical, not a forecast and not
investment advice. Undertow never places orders.

## Rules

1. **This folder is machine-generated.** Write your own notes outside `Undertow/`, or under the `## My notes`
   heading of a note here (Undertow creates that heading once and never touches anything below it).
2. **Never edit between `<!-- undertow:begin -->` and `<!-- undertow:end -->`.** That block is regenerated. If you
   do edit it, Undertow stops updating that note and writes its new version to `Undertow/_conflicts/` instead.
   Resolve by merging and deleting the conflict file yourself (Undertow never deletes anything).
3. **Never edit journal sealed fields** (every frontmatter key of a `Journal/` note that does not start with
   `outcome_`). They mirror the tamper-evident hash chain of the forward signal journal.
4. **Never invent filings.** Every signal note links to its filing on SEC EDGAR (`edgar_url`); cite that link.
5. **Numbers are historical or hypothetical.** Event-study results are averages over past filings; journal outcomes
   and the paper portfolio are hypothetical simulations. Do not phrase any of it as a recommendation or a forecast.
6. Extra frontmatter keys you add to a machine note are kept.

## Folders and note types

All notes have lowercase snake_case frontmatter with `type`, `source: undertow` and `generated_at` (ISO UTC).
Dates are ISO (`YYYY-MM-DD`), timestamps ISO UTC.

| Path | `type` | Updated |
|---|---|---|
| `Tickers/<SYMBOL>.md` | `ticker` | generated block refreshed; `## My notes` never touched |
| `Signals/<YYYY-MM-DD>-<SYMBOL>-<form>-<accession suffix>.md` | `signal` | written once, never rewritten |
| `Journal/<entry id>.md` | `journal` | sealed keys written once; only `outcome_*` keys and the outcome block update |
| `Briefs/<YYYY-MM-DD>.md` | `brief` | today's (UTC) brief refreshed; past briefs frozen |
| `Studies/<name>.md` | `study` | refreshed when the study file changes |
| `Paper/working-paper.md` | (none) | copy of the working paper |
| `Newsletter/<issue id>.md` | `newsletter` | written once (copy of the archived issue) |
| `Bases/*.base` | | Obsidian Bases views over the notes above |
| `index.md` | `index` | catalog, rewritten only when it changes |
| `log.md` | | append-only, one line per export run that changed something |
| `_conflicts/` | | new content for notes whose generated block was edited by hand |

### ticker
`ticker`, `cik`, `company`, `size_bucket` (nano < $50M, micro < $300M, small < $2B public float, mid, large),
`public_float_usd`, `last_filing`, `active_signals` (signal codes in the lookback window), `journal_open` (journal
entries still waiting or open), `watchlist`, `updated`, `undertow_hash` (sha256 of the generated block). Body:
recent signal filings table linking to signal notes, dilution and runway arithmetic from cached SEC XBRL data,
Edge Lab evidence lines.

### signal
`ticker` (`"[[SYMBOL]]"`), `form`, `items` (8-K items), `accession`, `filed_at`, `edgar_url`, `signals` (codes, most
severe first), `signal_names`, `direction` (expected direction prior: `+`, `-` or `?`), `severity` (1-3),
`size_bucket`, evidence for the primary signal in that bucket (`bucket`, `horizon_days`, `n`, `mean_abnormal`,
`excess_vs_baseline`, `t_stat`, `t_stat_clustered`, `significant`, `net`; null when there is no result),
`forward_test` (true for a live forward test of a pre-registered finding), `journal_id` when journaled. Body: a short
excerpt (never the full filing), the EDGAR link, the evidence sentence labelled "Historical event-study result
(hypothetical, not a forecast)", caveats.

### journal
Sealed: `entry_id`, `day` (UTC day recorded), `ticker`, `signal`, `signal_name`, `signals`, `direction`,
`horizon_days` (evaluation horizon), `expected` (historical mean abnormal return at that horizon), `expected_basis`,
`forward_test`, `article_id`, `cik`, `form`, `severity`, `size_bucket`, `public_float`, `filed_at`, `created_at`,
`borrow_fee`, `borrow_available`, `borrow_snapshot`; `sealed_day` and `seal_hash` (that day's hash in the journal
chain) are filled in once, when the day is sealed. Updatable: `outcome_status`, `outcome_resolved`,
`outcome_entry_date`, `outcome_abn_1`, `outcome_abn_5`, `outcome_abn_20` (hypothetical abnormal returns vs IWM),
`outcome_label`, `outcome_hash`.

### brief
`date`, `signals_count`, `tickers`, `forward_test_signals`, `paper_portfolio_value`, `paper_portfolio_return`,
`paper_label` (hypothetical). Body: that day's signal notes, journal entries recorded/sealed that day, the
hypothetical paper portfolio change.

### study
`study`, `study_file`, `study_generated_at`, `n_results`, `n_significant`. Body: headline results table (historical,
hypothetical) and a link to [[working-paper]].

## Writing a thesis note Undertow reads back

Put it anywhere **outside** `Undertow/` (and outside dot-folders), as a `.md` file under 1 MB, with frontmatter:

```yaml
---
type: thesis            # or: tags: [undertow/thesis]  (a "#undertow/thesis" tag works too)
ticker: ABCD            # "[[ABCD]]" or a list also work
title: Why ABCD's runway matters
updated: 2026-10-21
---
```

Undertow lists these (title, path, ticker, updated, tags and the first ~600 characters) next to the ticker. It only
parses the frontmatter; it never runs anything in a note. Notes with malformed frontmatter are skipped.
