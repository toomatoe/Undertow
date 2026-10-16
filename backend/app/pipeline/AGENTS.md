# backend/app/pipeline/: ingest cycle

Turns `RawArticle`s from `app/sources/` into stored, tagged, sized, enriched `Article` rows and
pushes live updates to browsers.

## Ingest cycle (`ingest.run_ingest`)

Runs in a worker thread (`asyncio.to_thread`) from the scheduler or `POST /api/ingest`. A module
`threading.Lock` allows one cycle at a time; a second caller gets `{"status": "already_running"}`.

1. **Fetch**: for each source from `build_sources(settings, universe)` (Alpaca if enabled, EDGAR if
   enabled, then every RSS feed): `source.fetch()`. One `IngestRun` row per source; an exception rolls
   back that source and is recorded in `IngestRun.error`, other sources continue.
2. **Dedupe -> tag -> store**: raws sorted oldest first, each through `store()`:
   `is_duplicate()` (url hash, then title hash within `TITLE_DEDUPE_WINDOW` = 2 days) ->
   merge source tickers with `tag_tickers(title + snippet)` (source tickers win via `setdefault`) ->
   insert `Article` with `signals` and `severity = max(ALL_SIGNALS[c].severity)`.
3. **Broadcast new**: after each insert commits, `broadcaster.publish("article", {"id": ...})`.
4. **Filing text** (if `edgar_enabled`): `fetch_bodies()` downloads the key document for up to
   `FILING_TEXT_MAX_PER_CYCLE` signal-bearing filings with `body IS NULL`, most severe first. Failure
   stores `body = ""` so it is not retried. Sleeps 0.25 s per filing (SEC rate limit).
5. **Enrich** (if an `Enricher` exists): `enrich_pending()` takes up to `ENRICH_MAX_PER_CYCLE` rows with
   `enriched_at IS NULL`, ordered `severity DESC NULLS LAST, published_at DESC`, passing `body`.
6. **Broadcast updated**: each enriched row -> `broadcaster.publish("article_updated", {"id": ...})`.

At startup `backfill_signals()` derives `form`/`signals`/`severity` for EDGAR rows stored before signals
existed, by parsing the `"FORM: Company (items ...)"` title.

## Modules

**dedupe.py**: `canonical_url()` lowercases scheme/host, strips trailing slash, fragment and tracking
params (`utm_*`, `mc_*`, `fbclid`, `gclid`, `cmpid`, `mod`, `yptr`, `ncid`...), sorts the query.
`url_hash()` = SHA-1 of that. `title_hash()` = SHA-1 of lowercase alphanumeric words (catches syndication).

**tickers.py**: `TickerUniverse` from SEC `company_tickers.json`, cached in `DATA_DIR` and refreshed
weekly (`CACHE_MAX_AGE`); `load()` never raises (empty universe if offline). `-` in tickers becomes `.`.
`tickers_for_cik()` returns only the primary listing. **Precision-first tagging:** `tag_tickers()` only
accepts cashtags (`$AAPL`) and exchange notation (`(NASDAQ: GOOGL, GOOG)`), validated against the universe
when it is loaded. No bare-name or bare-symbol matching (Target, Visa, "AAPL" in prose): that is left to
the LLM, whose tickers are also checked against the universe and stored with method `"llm"`.

**companies.py**: size from SEC XBRL `dei:EntityPublicFloat` frames (`FRAME_URL`, `CY{year}Q2I`), cached as
`public_float_CY{year}Q2I.json`. `load_latest_floats()` merges the last three years, newest wins.
`bucket_for()` buckets on public float: `nano` < $50M, `micro` < $300M, `small` < $2B, `mid` < $10B,
`large`; `None` if missing or <= 0. `BUCKET_NAMES` validates the `size` query param. `sync_companies()`
deletes and rewrites the `companies` table. Public float understates market cap for insider-heavy firms.

**signals.py**: shared by live alerts and the event study. `SignalDef(code, label, direction, severity, why)`;
direction `"-"`, `"+"` or `"?"` is a prior (it also fixes the event study's trade direction), severity 1-3
ranks alerts. `ITEM_SIGNALS` maps 8-K items (7.01, 8.01, 9.01 deliberately excluded); `FORM_SIGNALS` maps
424B4/424B5/S-1/S-3/SCHEDULE 13D/SC 13D. Codes can be shared (both 424Bs -> `offering_priced`).
`ALL_SIGNALS` is keyed by code. `signals_for_filing(form, items)` strips `/A`, dedupes by code, sorts by
severity desc. `EVENT_FORMS` is the live EDGAR form list. `signal_dict()` feeds `SignalOut`.

**enrich.py**: `Enricher(api_key, model).enrich(title, snippet, source_name, body=None) -> Enrichment | None`.
- Structured outputs: `output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}`;
  the schema enums `EVENT_TYPES` and `FLAGS`. Result validated by the `Enrichment` pydantic model; tickers
  uppercased, `$` stripped. `body` truncated to `BODY_CHARS` (8000).
- Model: `ENRICH_MODEL`, default `claude-opus-5-5`; `claude-haiku-5-5` is ~40x cheaper per token (measure
  before switching). Every row stores `enrich_model` so results can be compared or re-run.
- Refusal fallback: models starting with `_FALLBACK_MODELS` go through
  `client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", ...)`;
  others use `client.messages.create`. Transient errors (rate limit, connection,
  API status) return `None` (row stays pending). Permanent ones (`refusal`/`max_tokens`, empty or invalid
  output) raise `EnrichmentFailed`; `enrich_pending` then sets `enriched_at` and
  `enrich_model = "<model> (failed: <reason>)"` with a null summary, so the row is not retried.
- Flags (`going_concern`, `reverse_split`, `atm_program`, ...): only when the text explicitly states them.
- Sentiment is scored from text available at ingest time (no look-ahead for later backtests).

**events.py**: `Broadcaster` in-process pub/sub, singleton `broadcaster`. `bind_loop()` at startup;
`publish()` is thread-safe (`call_soon_threadsafe`) and a no-op before binding (e.g. in tests).
Per-subscriber `asyncio.Queue(maxsize=200)`, oldest message dropped for slow clients. `/api/stream` in
main.py sends `retry: 5000`, then `event: article|article_updated` with `data: {"id": N}`, keepalive
comments every 15 s. Payloads carry only ids; clients refetch `/api/articles/{id}`. Single process only.

## Invariants

- **EDGAR item mapping is authoritative over the LLM `event_type`**: `enrich_pending` sets
  `article.event_type = article.event_type or result.event_type`. Never let enrichment overwrite it.
- Source-provided tickers (`vendor`, `edgar`) take precedence over text tags; LLM tickers only add.
- Tagging stays precision-first; validate any new ticker path against `TickerUniverse`.
- `Article.signals` holds codes that exist in `ALL_SIGNALS`; `ArticleOut.expand_signals` silently drops unknown ones.
- `EVENT_TYPES` values are shared by `ITEM_EVENTS`/`FORM_EVENTS` in `sources/edgar.py` and the UI filter.
- Changing `signals.py` changes the event study's test set; see `app/research/AGENTS.md`.
- All SEC requests send `settings.sec_user_agent` and stay under 10 req/s.
