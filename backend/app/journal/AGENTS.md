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

- **Append-only.** Identity fields (ticker, signals, size, filed_at, borrow at record time) are never changed after insert. Only marking fields (`status`, `entry_*`, `abn_*`, `marked_at`) are updated. Once a day is sealed (`digest.py`), changing or deleting one of its record-time fields makes `verify_chain` fail for that day.
- **Entry timing must match the backtest base case** (`ENTRY_DELAY = 1`, the same `day0_index`). If the backtest base changes, change both and note it. Comparing live with backtest only makes sense with identical timing.
- **Size bucket is frozen at record time.** Today's float is used for new signals; it is not recomputed later.
- **Borrow for entries backfilled at launch** comes from the first snapshot, up to 3 days after filing. All later entries are recorded the same day.
- **The primary signal is `signals[0]`**, i.e. the most severe. The summary and filters group by it.

## Tamper-evident seal (`digest.py`)

A daily SHA-256 hash chain over the journal, so the track record can't be silently edited after the fact.
The head hash is printed in every weekly newsletter issue (immutable, dated archive = outside witness).

| Function | What |
|---|---|
| `seal_through(session, data_dir, through_day, now=None)` | Appends one chain line per unsealed UTC day, from the first journal day (or the day after the last sealed day) through `through_day`. `through_day` is capped at **yesterday (UTC)**: today and future days are never sealed. Idempotent (sealed days are skipped). Days with no entries are sealed with `count: 0` so the chain is contiguous. Raises `ChainError` and appends nothing if the file is malformed. Returns the new lines. |
| `verify_chain(session, data_dir)` | Recomputes every sealed day from the DB. `{ok, days, head_hash, head_day, first_mismatch: {day, expected, actual} \| None, broken_link: {day, expected_prev, actual_prev, reason} \| None, late_days[]}`. `expected` = hash in the file, `actual` = recomputed. `broken_link` covers removed/reordered lines, day gaps, malformed or torn lines, and entries recorded before the first sealed day. |
| `export_day(session, data_dir, day)` | `{day, prev_hash, hash, entries}` for a sealed day (None otherwise): everything a third party needs to recompute the hash. |
| `chain_head(data_dir)` | `{head_hash, head_day, days}`, or None when nothing is sealed (or the file is unreadable). Used by the newsletter. |
| `canonical_entries(session, day)`, `day_hash(entries, prev_hash, day)` | The canonical form, below. |

Helpers in `service.py`: `entries_recorded_on(session, day)` (by UTC `created_at`, sorted by id), `first_recorded_day(session)`, `recorded_day(entry)`.

CLI: `python -m app.journal.digest seal [--through YYYY-MM-DD]` (default yesterday UTC) `| verify` (exit 1 when not ok) `| export YYYY-MM-DD`.
Routes and the scheduler hook are wired elsewhere (main.py is not owned by this module); call `seal_through(..., yesterday)` once a day, a few minutes after 00:00 UTC.

**Chain file** `{data_dir}/journal_chain.jsonl`: one compact JSON line per sealed day
`{day, prev_hash, hash, count, sealed_at, sealed_late}`. Genesis `prev_hash` is 64 zeros. Append-only (opened in `a`
mode, flush + fsync per line), never rewritten. One writer per process (module lock); don't run the CLI `seal` and the
scheduler at the same moment.

**Canonical form.** A day = the entries whose `created_at` falls on that UTC day, sorted by `id`, each reduced to the
record-time fields `RECORD_FIELDS`: `id, article_id, ticker, cik, form, signals, primary_signal, direction, severity,
size_bucket, public_float, filed_at, created_at, borrow_fee, borrow_available, borrow_snapshot`.
Datetimes are UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ` (naive DB values are treated as UTC), floats `round(x, 8)`, lists keep
their order. `hash = sha256(json.dumps({"day", "prev", "entries"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True))`.

**Not covered:** the marking fields (`status`, `entry_date`, `entry_price`, `raw_entry_price`, `abn_*`, `marked_at`).
They are later, deterministic computations from prices and the sealed `filed_at`, so anyone can redo them; updating
them never breaks the chain. The model has no accession column (the filing is identified by `article_id`, `cik`,
`form`, `filed_at`) and no stored Edge Lab expectation at record time, so neither is sealed.

**Late seals.** `sealed_late: true` when the seal's UTC date is more than 2 days after the sealed day (e.g. Oct 13
sealed on Oct 16). The Oct 13-19 2026 launch backfill is flagged this way on purpose: it was sealed after the fact.
An entry inserted in the second before midnight but committed after that day was sealed would show up as a mismatch,
which is why sealing runs a few minutes after midnight.

**Verify by hand** (standard library only), from `python -m app.journal.digest export 2026-10-14 > day.json`:

```python
import hashlib, json
d = json.load(open("day.json"))
payload = {"day": d["day"], "prev": d["prev_hash"], "entries": d["entries"]}
h = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
assert h == d["hash"]   # and d["prev_hash"] must equal the previous day's hash; the head must match the newsletter
```

Tests: `tests/test_journal_digest.py` (links, idempotence, today never sealed, late flag, record-field tampering,
mark updates, removed lines, torn file, independent hashlib recompute).

## API

- `GET /api/journal?signal=&size=&status=&limit=`: `{total, since, entries[]}`, newest first. Each entry includes `title`, `filing_url`, `signal_label`.
- `GET /api/journal/summary`: `{rows[], marked}`.
- UI: `frontend/src/app/track-record/` with `components/track/`.
