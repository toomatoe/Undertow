# backend/app/newsletter: weekly "Small-Cap Filing Radar"

The regular publication behind the publisher's exclusion (`docs/PRODUCT_RESEARCH.md` section 4, distribution item 9).
Built automatically from our own data, archived as files, exported as Markdown and email-safe HTML for pasting into
Substack/Beehiiv. Email delivery (double opt-in list, fan-out of each new issue, daily digest) lives in
`app/delivery/` (see [delivery/AGENTS.md](../delivery/AGENTS.md)); it is off unless SMTP is configured.

## Flow (`service.py`)

| Function | What |
|---|---|
| `build_issue(session, data_dir, week_end, *, user_agent, public_base_url, now=None)` | Dict for the 7 ET calendar days ending `week_end` (normally a Sunday). `now` cuts the window for a preview (`partial: true`). Id = ISO week of `week_end`, e.g. `2026-W41`. |
| `render_markdown(issue)` / `render_html(issue)` | Pure functions of the dict. HTML: one 640px table column, inline styles only, no `<style>`/`<script>`/`<link>`/classes, light background. |
| `generate(..., force=False)` | Build + save `{data_dir}/newsletters/{id}.json|.md|.html`. **An existing issue is returned untouched unless `force=True`.** JSON is written last, so its presence means the issue is complete. |
| `ensure_latest(session, data_dir, today=None)` | Scheduler hook (`main.newsletter_cycle`, after each slow ingest cycle): builds the most recently *completed* week (Sunday strictly before today, ET) if missing. |
| `preview(session, data_dir, now=None)` | Current week so far, never saved. |
| `list_issues`, `load_issue`, `load_text` | Archive reads. Issue ids are validated against `^\d{4}-W\d{2}$` (no path traversal). |

## Sections

1. **Headline:** signal filings (articles with `severity`) whose ticker is a nano/micro/small `Company`, by severity and size.
2. **Top filings:** severity 3 then 2, newest first, max 20. Edge Lab stat = first signal with a 20-day row in `{data_dir}/event_study.json` for that size (same lookup as `main.to_out`).
3. **Dilution watch:** 2+ offering-type signals (`OFFERING_SIGNALS`) this week, or a priced offering with runway < 6 months from `fundamentals.company_profile` (max 15 lookups, priced offerings first; errors are logged and skipped). Cash figures older than 400 days are shown as stale and never qualify.
4. **Serious halts:** `trading_halts` with a `SERIOUS` reason code; mid/large caps excluded, unknown size kept.
5. **Track record:** `journal.summary` rows with `n_20 >= 5` (small caps), else "still collecting: N recorded, first 20-day results due ~DATE" (earliest open entry + 21 weekdays). Reflects the journal at build time.
   `track_record.seal` = `journal.digest.chain_head(data_dir)` (`{head_hash, head_day, days}`) or `null` when no chain
   exists. Both renderers print one line via `seal_line(issue)`: "Track-record seal through DAY: <first 16 hex>… (N days;
   verify at PUBLIC_BASE_URL/track-record)". This makes each dated, immutable issue an outside witness of the chain head
   (format and hand verification: journal/AGENTS.md). Issues archived before this field have no `seal` key and render
   without the line; they are never regenerated to add it. All other `track_record` keys are unchanged (the frontend reads them).
6. **Research note:** `key_finding.text` from `{data_dir}/backtests/report_latest.json`, trimmed to ~520 chars, sentences with banned words dropped. Omitted if the file is missing.
7. **Coverage note** when live filing collection began after the week started (an empty week is then not a quiet week), links (`PUBLIC_BASE_URL`) and the disclaimer, including the 48-hour no-trading policy from `/legal/disclaimer`.

## Content rules (strict)

- Impersonal facts and historical statistics only. No buy/sell language, price targets, "opportunity" or earnings claims.
- Every Edge Lab / backtest / journal number is labelled historical, hypothetical or simulated.
- Don't print signal `why` text: some of it ("can sell shares...") trips the banned-word check.
- `banned_words()` regex matches word stems: `buy*`, `sell*`, `short it`, `target*`, `opportunit*`, `guarantee*`, `profit*`
  (word start boundary, any case), so "profitable", "selling", "targets" are caught. `tests/test_newsletter.py` keeps
  a copy of the pattern, asserts it equals `nl.BANNED.pattern`, and asserts rendered output is clean.
- `flagged_words(issue)` scans rendered Markdown **and** HTML of a copy with third-party names blanked (filing
  `company`/`ticker`, which already carries the filing-title fallback, dilution `company`/`ticker`, halt `name`/`symbol`),
  so real names like "Sellas" or a ticker "BUYZ" don't count; only our own prose is flagged. `build_issue` stores the
  result in `issue["flagged_words"]` (`[]` normally; absent on issues archived before this field) and logs at **error**
  level when non-empty. It never refuses to build or save: that would block the week forever.
- Missing filing `form` renders as "filing" in both renderers' dilution links (top filings say "Form n/a"); never "None".
- `_research_note` logs at info how many sentences it dropped for banned words.

## Run

```bash
docker compose run --rm api python -m app.newsletter.build                        # last completed week
docker compose run --rm api python -m app.newsletter.build --week-end 2026-10-11 [--force]
docker compose run --rm api python -m app.newsletter.build --preview              # print counts, save nothing
```

## API / UI

- `GET /api/newsletter/issues`, `GET /api/newsletter/{id}` (+ `markdown`), `GET /api/newsletter/{id}.html`, `POST /api/newsletter/preview` (+ `markdown`, `html`).
- UI: `frontend/src/app/newsletter/` with `components/newsletter/`.
