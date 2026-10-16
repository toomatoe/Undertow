# frontend/: Next.js UI

Next.js 15.5 App Router, React 19, TypeScript (strict). No UI library, no state library, no CSS framework:
plain components plus `src/app/globals.css`. Path alias `@/*` -> `src/*`.

## Layout

```
src/app/layout.tsx          root layout: Geist fonts, <Nav/>, globals.css
src/app/page.tsx            /                -> <NewsFeed/>
src/app/signals/page.tsx    /signals         filing signals (default size "nano,micro,small")
src/app/lab/page.tsx        /lab             Edge Lab: event-study results
src/app/ticker/[symbol]/page.tsx  /ticker/X  ticker detail (params is a Promise, unwrapped with use())
src/app/research/page.tsx   /research        static "planned" page (AI research assistant)
src/app/backtest/page.tsx   /backtest        backtest report + live-readiness log (components in src/components/backtest/)
src/app/trading/page.tsx    /trading         static "not built" page (paper trading plan)
src/components/             shared client components
src/lib/api.ts              the only API client
src/lib/format.ts           formatting helpers and label maps
```

Data pages are client components (`"use client"`) that fetch in `useEffect`; there are no server
components fetching data and no API routes in Next.

## Pages

- `/` `NewsFeed`: filters (search debounced 300 ms, ticker, size, source, sentiment, event type),
  `before`-cursor pagination ("Load older"), live SSE inserts, `Sidebar` (trending tickers, source status,
  "ingest now").
- `/signals`: `api.signals()` with size / min_severity / signal (from `api.signalCatalog()`) / watchlist
  filters, `WatchlistPanel`, legend. SSE `article` events trigger a reload debounced by 3 s.
- `/lab`: `api.eventStudy()`; tiles, "what survived", per-bucket `DivergingChart` of `mean_net` with a
  5d/20d toggle, coverage/survivorship table, full results table, caveats. 404 -> "No study yet" message.
- `/ticker/[symbol]`: `api.ticker(symbol, days)`, size/float, watchlist toggle, daily coverage bars, articles.
- `/backtest`: `api.backtestReport()` + `api.backtestRuns()`. Verdict and key finding first, then A/B tiles,
  friction waterfall, borrow fees, equity/drawdown charts (inline SVG `TimeChart`), readiness checklist,
  real-money projection, stress, robustness, trade log (CSV export), run log, assumptions. Types `BacktestReport`
  etc. mirror the JSON from `backend/app/backtest/report.py`.
- `/research`, `/trading`: placeholders. Trading must stay paper-only; agents never place orders.

## Components

| File | Role |
|---|---|
| `Nav.tsx` | Header tabs from `TABS`; `/ticker/*` highlights News. Add new pages here |
| `NewsFeed.tsx` | News tab body; owns the SSE subscription for `/`. Has its own `EVENT_TYPES` list for the filter |
| `ArticleCard.tsx` | One article/filing: badges, sentiment, signals, AI flags, tickers with size, `EvidenceLine` |
| `Sidebar.tsx` | Trending tickers (`api.trending(hours)`), `api.status()`, manual `api.ingest()` |
| `WatchlistPanel.tsx` | List/add/remove watchlist symbols; `onChange` callback for the parent |

## API client (`src/lib/api.ts`)

- `API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"`. All requests use
  `cache: "no-store"` and throw `"<status> <text>"` on non-2xx (pages check `startsWith("404")`).
- `api.*` methods: `articles`, `article`, `signals`, `signalCatalog`, `eventStudy`, `watchlist`, `watch`,
  `trending`, `ticker`, `status`, `ingest`, plus `streamUrl`. Never call `fetch` from components.
- Types mirror `backend/app/schemas.py`: `Ticker` = `TickerOut`, `Signal` = `SignalOut`, `Evidence`,
  `Article` = `ArticleOut`, `ArticlePage`, `TrendingTicker`, `TickerDetail`, `Status`. `EventStudy` /
  `StudyResult` mirror the JSON written by `backend/app/research/eventstudy.py` (not a pydantic model).
  When a backend field changes, change the type here in the same commit.
- `ArticleFilters` is serialized by `query()`, which drops `undefined`, `null` and `""`. To ask for every size, send
  `size=all` (the "All sizes" option in `SIZE_FILTERS`); an empty value would let the backend default (`nano,micro,small`) apply.

## SSE

`new EventSource(api.streamUrl)`; events `article` (new row) and `article_updated` (enriched row), payload
`{"id": number}`. Refetch with `api.article(id)`. Always `es.close()` in the effect cleanup. The server
sends `retry: 5000` and keepalives; `onopen`/`onerror` drive the LIVE/OFFLINE badge in `NewsFeed`.

## Styling (`src/app/globals.css`)

- Tokens on `:root`: `--bg`, `--panel`, `--panel-2`, `--border`, `--text`, `--muted`, `--accent`, `--pos`,
  `--neg`, `--neu`, `--warn`, `--radius`. Dark is the default; `prefers-color-scheme: light` overrides.
  Use tokens, not literal colors.
- Sentiment classes come from `sentimentClass()` in format.ts (`sent-pos|sent-neg|sent-neu|sent-none`,
  +-0.15 thresholds matching the backend label rule).
- **Edge Lab diverging palette** `--div-pos`, `--div-neg`, `--div-mid` (light default, dark override, under
  `/* --- Signals --- */`) is validated for colorblind readability in both themes. Don't change it casually;
  if you must, re-check contrast and CVD simulation for both modes.
- Size labels/filters: `SIZE_LABELS`, `SIZE_FILTERS` in format.ts must match backend `BUCKETS`.

## Verify

```bash
npm --prefix frontend install
cd frontend && npx tsc --noEmit          # type check
npm --prefix frontend run lint
npm --prefix frontend run build          # only when the dev server is NOT running
```

Do not run `next build` while `npm run dev` is running: both write `frontend/.next`, and the build clobbers
the dev server's output (broken pages until restart). Stop the dev server first, or rely on `tsc` + lint.
Visual check: dev server on :3000 (preview config `frontend` in `.claude/launch.json`) with the API on :8000.
