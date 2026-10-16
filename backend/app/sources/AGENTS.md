# backend/app/sources/: data source adapters

Each adapter fetches one external feed and returns `list[RawArticle]`. Adapters do no DB work,
no dedupe across cycles and no LLM calls; `pipeline/ingest.py` does all of that.

## The contract (`base.py`)

```python
class Source(Protocol):
    name: str                          # shown in /api/status and stored in IngestRun.source_name
    def fetch(self) -> list[RawArticle]: ...
```

`RawArticle` fields:

| Field | Rule |
|---|---|
| `url`, `title` | required; items missing either are skipped by every adapter |
| `published_at` | tz-aware UTC `datetime` (use `rss.entry_published`, which falls back to now) |
| `source` | `"rss" \| "edgar" \| "alpaca"` (`Article.source` is `String(32)`, used by filters and UI labels) |
| `source_name` | human label, e.g. `"SEC EDGAR"`, `"CNBC Markets"`, `"Benzinga (Alpaca)"` |
| `snippet` | plain text via `clean_html(text, limit=600)`; never full article text |
| `author` | optional, truncated to 256 on store |
| `tickers` | `set[(symbol, method)]` the source already knows (`"vendor"`, `"edgar"`). Text tagging adds more later |
| `event_type` | optional, must be one of `pipeline.enrich.EVENT_TYPES`; if set, enrichment won't overwrite it |
| `cik`, `form`, `signals` | SEC filings only; `signals` is a list of codes from `pipeline/signals.py` |

`fetch()` may raise (e.g. `httpx` errors): `run_ingest` catches per source, records `IngestRun.error`,
and moves on. Don't swallow errors silently inside `fetch()`.

## rss.py

- `RssSource(name, url, user_agent)`: one instance per entry in `settings.rss_feeds`
  (`DEFAULT_RSS_FEEDS` in config.py). Sends `settings.sec_user_agent` as User-Agent, follows redirects.
- Helpers reused elsewhere: `clean_html(text, limit)` (strip tags, unescape, collapse whitespace,
  truncate) and `entry_published(entry)` (feedparser `published_parsed`/`updated_parsed` -> UTC).

## edgar.py

**Multi-form feeds.** `EdgarSource(user_agent, universe, forms=EVENT_FORMS)` calls
`https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=<form>&owner=include&count=100&output=atom`
once per form in `EVENT_FORMS` (`8-K, 424B4, 424B5, S-1, S-3, SCHEDULE 13D`), sleeping 0.2 s between calls
(SEC fair access is under 10 req/s). The `type` filter is loose, so entries whose parsed form != the
requested form are dropped. Entries are deduped within the cycle by accession number (`_ACCESSION_RE`).

**`parse_entry(entry, universe)`** parses titles like `8-K - Apple Inc. (0000320193) (Filer)`:
- Amendments (`/A`) are skipped.
- **13D Subject/Filer rule:** a Schedule 13D appears once per party. Keep only the `(Subject)` row (the
  company the stake is in); drop the `(Filer)` row (the investor). Every other form keeps only `(Filer)`.
- Tickers: `universe.tickers_for_cik(cik)` (primary listing only), method `"edgar"`.
- 8-K items come from the summary (`parse_items`, regex `Item \d.\d\d`); title becomes
  `"8-K: Company (items 2.02, 9.01)"`. `backfill_signals` in ingest.py re-parses this title format, so keep it.
- `event_type`: 8-K -> `event_from_items(items)` via `ITEM_EVENTS` (first mapped non-"other" item wins);
  other forms -> `FORM_EVENTS`. `signals` -> `signals_for_filing(form, items)`.

**Filing text.** `fetch_filing_text(index_url, user_agent, limit=15000)`: takes the filing's `-index.htm`
URL (the Atom link stored as `Article.url`), reads `{folder}/index.json`, picks a document with
`pick_document()` (prefers an `EX-99` press-release exhibit, else the first non-skipped `.htm`, else
`primary_doc.xml` for XML-only filings such as post-2025 Schedule 13D), strips script/style and returns
plain text. Two requests per filing. Called from `pipeline.ingest.fetch_bodies`, not from `fetch()`.

## alpaca.py

- `AlpacaNewsSource(key_id, secret_key)`, `name = "Alpaca / Benzinga"`. Enabled only when both
  `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` are set (`settings.alpaca_enabled`).
- GET `https://data.alpaca.markets/v1beta1/news` with `limit=50, sort=desc, include_content=false`.
  Headlines + summary only. Symbols become `(symbol, "vendor")` tickers, which win over text tagging.
- News data only. Nothing in this repo places orders; do not add order endpoints here.

## Adding a source

1. New module with a class exposing `name` and `fetch() -> list[RawArticle]`. Use `httpx` with a timeout
   (existing adapters use 20 s), reuse `clean_html` / `entry_published`, keep snippets short.
2. Credentials/URLs as fields on `Settings` in `app/config.py` (+ an `*_enabled` property) and a commented
   entry in `.env.example`. Never commit keys.
3. Instantiate it in `build_sources()` in `app/pipeline/ingest.py`.
4. If `source` is a new value, add it to `SOURCE_LABELS` (`frontend/src/lib/format.ts`) and the source
   dropdown in `frontend/src/components/NewsFeed.tsx`; update the `Article.source` comment in models.py.
5. Test the parser with a canned payload in `backend/tests/` (no network), like `test_pipeline.py`.
6. Respect the provider's rate limits and terms; SEC requests must send `settings.sec_user_agent`.
