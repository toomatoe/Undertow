# backend/app/journal: forward signal journal (track record)

A live, timestamped record of every signal-bearing SEC filing. It does two jobs:

- **Forward test:** do Edge Lab patterns hold on filings nobody had seen yet?
- **Public track record:** the product differentiator found in `docs/PRODUCT_RESEARCH.md`.

No orders, no money.

## Flow (`service.py`)

| Step | When | What |
|---|---|---|
| `record_new(session, data_dir)` | every slow ingest cycle (`main.journal_cycle`) | One `JournalEntry` per EDGAR article with `severity` set and a ticker whose `Company.size_bucket` is known. Captures IBKR borrow fee and availability if the latest snapshot is ≤ 36 h old. Idempotent (unique `article_id`). |
| `mark(session, data_dir)` | at most once per UTC day (`state.journal_marked`) | For rows in `waiting`/`open`: entry = adjusted close on **day 0 + 1**, then abnormal return vs IWM at +1/+5/+20 trading days. Prices go to `data/prices_live` (Yahoo, personal use, cache key changes daily). |
| `summary(session, expected)` | `GET /api/journal/summary` | Per (primary signal, size): n, mean/median/hit rate per horizon, next to the Edge Lab `mean_abnormal` for the same signal/size/horizon. |

`mark_entry(entry, series, bench, today)` is a pure function of its inputs; test it with synthetic series (`tests/test_journal.py`).

## Status machine

`waiting` (day 0 + 1 hasn't printed) → `open` (entry priced, horizons filling) → `complete` (20-day result in).

Side exits:
- `data_ended`: no print for 10+ days before +20.
- `no_data`: never priced after 10 days.

## Invariants

- **Append-only.** Identity fields (ticker, signals, size, filed_at, borrow at record time) are never changed after insert. Only marking fields (`status`, `entry_*`, `abn_*`, `marked_at`) are updated.
- **Entry timing must match the backtest base case** (`ENTRY_DELAY = 1`, the same `day0_index`). If the backtest base changes, change both and note it. Comparing live with backtest only makes sense with identical timing.
- **Size bucket is frozen at record time.** Today's float is used for new signals; it is not recomputed later.
- **Borrow for entries backfilled at launch** comes from the first snapshot, up to 3 days after filing. All later entries are recorded the same day.
- **The primary signal is `signals[0]`**, i.e. the most severe. The summary and filters group by it.

## API

- `GET /api/journal?signal=&size=&status=&limit=`: `{total, since, entries[]}`, newest first. Each entry includes `title`, `filing_url`, `signal_label`.
- `GET /api/journal/summary`: `{rows[], marked}`.
- UI: `frontend/src/app/track-record/` with `components/track/`.
