# frontend/: Next.js UI

Next.js 15.5 App Router, React 19, TypeScript (strict). No UI library, no state library, no CSS framework:
plain components plus `src/app/globals.css`. Path alias `@/*` -> `src/*`.

## Layout

```
src/app/layout.tsx          root layout: Geist fonts, <Nav/>, globals.css
src/app/page.tsx            /                -> <NewsFeed/>
src/app/signals/page.tsx    /signals         filing signals (default size "nano,micro,small")
src/app/lab/page.tsx        /lab             Edge Lab: event-study results
src/app/ticker/[symbol]/           /ticker/X  server-rendered SEO ticker page (ISR 15 min), see "Server-rendered pages"
  not-found.tsx                    404 page; catches notFound() thrown by (view)/layout.tsx
  (view)/layout.tsx                404 gate: parseSymbol + getTicker before anything streams (real HTTP 404)
  (view)/page.tsx                  server component: metadata, canonical, JSON-LD, summary paragraph, server ArticleCards
  (view)/loading.tsx               skeleton (wraps only page.tsx)
  (view)/TickerView.tsx            client part: watch toggle, 7/30/90d window, coverage bars, articles
  (view)/summary.ts                factual summary sentences, meta description, dateModified (pure, dated text)
  (view)/symbol.ts                 parseSymbol(): route param -> symbol or null (no second decode)
src/app/newsletter/layout.tsx      /newsletter default title + description
src/app/newsletter/page.tsx        /newsletter archive + latest issue (server component, ISR 10 min)
src/app/newsletter/[issue]/        /newsletter/2026-W41  one issue (server component, ISR 1 h); same (view)/ + not-found.tsx
                                   pattern as the ticker page (layout.tsx gate via parseIssueId, loading.tsx, page.tsx)
src/app/sitemap.ts                 /sitemap.xml  static pages + /api/tickers/sitemap + archived issues (revalidate 1 h)
src/app/robots.ts                  /robots.txt   allow /, disallow /api/, points at the sitemap
src/app/research/page.tsx   /research        static "planned" page (AI research assistant)
src/app/track-record/page.tsx /track-record forward signal journal vs Edge Lab (components in src/components/track/)
src/app/backtest/page.tsx   /backtest        backtest report + live-readiness log (components in src/components/backtest/)
src/app/methodology/page.tsx /methodology  how every number is produced (keep in sync with backend logic)
src/app/legal/{disclaimer,terms,privacy}/page.tsx  DRAFT legal pages (DraftNotice until lawyer review)
src/app/trading/page.tsx    /trading         static "not built" page (paper trading plan)
src/components/             shared client components
src/lib/api.ts              the only browser API client
src/lib/server-api.ts       server-side fetch helpers (server components, generateMetadata, sitemap.ts), SITE_URL
src/lib/format.ts           formatting helpers and label maps
```

Most data pages are client components (`"use client"`) that fetch in `useEffect` through `api`. The exceptions are the
crawlable pages (`/ticker/[symbol]`, `/newsletter`, `/newsletter/[issue]`) plus `sitemap.ts`, which are server components
fetching through `src/lib/server-api.ts`. There are no API routes in Next.

## Server-rendered pages (SEO)

- `server-api.ts` helpers (`getTicker`, `getFundamentals`, `getHalts`, `getSitemapTickers`, `getNewsletterIssues`,
  `getNewsletterIssue`) return `Result<T>` (`{ok: true, data}` or `{ok: false, status, error}`, status 0 = network
  error/timeout) and never throw. They use `next: { revalidate }` and a timeout; most are wrapped in React `cache()`
  so layout, `generateMetadata` and page share one request.
- 404 gate: `(view)/layout.tsx` validates the param and fetches before anything streams, so an unknown ticker or
  issue gets a real HTTP 404 (a `notFound()` inside `page.tsx` would arrive after `loading.tsx` sent a 200). The
  `(view)` route group exists so the sibling `not-found.tsx` catches it. Invalid params 404 without an API call.
- Each page sets `metadataBase: new URL(SITE_URL)`, a canonical path, Open Graph/Twitter tags, and inline JSON-LD
  (`WebPage` + `Corporation` for tickers, `Article` in a `CreativeWorkSeries` for issues) with `<` escaped.
- Client panels accept server data: `DilutionPanel initialData`, `HaltsPanel initialData` skip their first fetch for
  that query. Dates/times rendered on both sides use a fixed locale and timezone (halts: US Eastern) so hydration matches.
- Ticker summary text (`summary.ts`) is facts only, every window written with explicit dates (pages are cached).
- Newsletter: the archive list is real links to `/newsletter/<id>`; old `/newsletter?issue=<id>` links (still used
  by the backend's `links.archive`) are redirected client-side by `NewsletterWorkspace` (`legacyQuery`).
- Never convert these pages to `useEffect` client pages: crawlers would lose the content and links.

## Pages

- `/` `NewsFeed`: filters (search debounced 300 ms, ticker, size, source, sentiment, event type),
  `before`-cursor pagination ("Load older"), live SSE inserts, `Sidebar` (trending tickers, source status,
  "ingest now").
- `/signals`: `api.signals()` with size / min_severity / signal (from `api.signalCatalog()`) / watchlist
  filters, `WatchlistPanel`, legend. SSE `article` events trigger a reload debounced by 3 s.
- `/lab`: `api.eventStudy()`; tiles, "what survived", per-bucket `DivergingChart` of `mean_net` with a
  5d/20d toggle, coverage/survivorship table, full results table, caveats. 404 -> "No study yet" message.
- `/ticker/[symbol]`: server-fetched ticker (90 days), fundamentals and halts; factual summary paragraph, then
  `TickerView` (watchlist re-checked in the browser, window switch re-fetches via `api.ticker`), `DilutionPanel` (server
  data, or client fetch if the server call failed with non-404, omitted without a CIK or on 404), `HaltsPanel`,
  coverage bars, articles, related links.
- `/newsletter`, `/newsletter/[issue]`: `NewsletterWorkspace` = `ArchiveList` sidebar + export toolbar (Copy Markdown,
  Download HTML, Open email version) + `IssueView`. "Preview this week so far" calls `api.newsletterPreview()` (POST,
  never archived). If the server could not reach the API, the workspace retries from the browser.
- `/backtest`: `api.backtestReport()` + `api.backtestRuns()`. Verdict and key finding first, then A/B tiles,
  friction waterfall, borrow fees, equity/drawdown charts (inline SVG `TimeChart`), readiness checklist,
  real-money projection, stress, robustness, trade log (CSV export), run log, assumptions. Types `BacktestReport`
  etc. mirror the JSON from `backend/app/backtest/report.py`.
- `/track-record`: `api.journal()` + `api.journalSummary()`; status tiles, live-vs-expected table ("too early" under
  5 results), nano-offering spotlight with a running-mean chart, filterable journal table with CSV.
- `/ticker/[symbol]` also renders `DilutionPanel` (`initialData` or `api.fundamentals()`): runway, cash, 1-year share change, offering history.
- Charts measure their container width. In a hidden/zero-width browser pane they render no SVG; that is expected, not a bug.
- `/research`, `/trading`: placeholders. Trading must stay paper-only; agents never place orders.

## Components

| File | Role |
|---|---|
| `Nav.tsx` | Header tabs from `TABS` (includes Newsletter); `/ticker/*` highlights News. Add new pages here |
| `NewsFeed.tsx` | News tab body; owns the SSE subscription for `/`. Has its own `EVENT_TYPES` list for the filter |
| `ArticleCard.tsx` | One article/filing: badges, sentiment, signals, AI flags, tickers with size, `EvidenceLine` |
| `Sidebar.tsx` | Trending tickers (`api.trending(hours)`), `api.status()`, manual `api.ingest()` |
| `Footer.tsx` | Site-wide footer with disclaimer line and legal/methodology links (in layout.tsx) |
| `DraftNotice.tsx` | Banner on legal pages until a lawyer reviews them; remove only after review |
| `HaltsPanel.tsx` | Trading halts (ticker-scoped or small caps today); optional `initialData`; refreshes every 60s; times in US Eastern |
| `DilutionPanel.tsx` | Runway, cash, share change, short interest, offering history on ticker pages; optional `initialData` |
| `newsletter/NewsletterWorkspace.tsx` | Archive + toolbar + issue body for both newsletter pages; preview, export, API retry, legacy `?issue=` redirect |
| `newsletter/ArchiveList.tsx` (+ `.module.css`) | Archive sidebar: links to issue pages, "Preview this week so far" button |
| `newsletter/IssueView.tsx` | Renders one issue (tiles, top filings, dilution watch, halts, track record, research note, disclaimer) |
| `newsletter/format.ts` | Plain helpers for server and client: `parseIssueId`, `issuePath`, `weekLabel`, `issueTitle`, `issueDescription`, `etTime`, `dayLabel`. Never add `"use client"` here |
| `backtest/`, `track/` | Charts and tables for `/backtest` and `/track-record` |
| `WatchlistPanel.tsx` | List/add/remove watchlist symbols; `onChange` callback for the parent |

## API client (`src/lib/api.ts`)

- `API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"`. All requests use
  `cache: "no-store"` and throw `"<status> <text>"` on non-2xx (pages check `startsWith("404")`).
- `api.*` methods: `articles`, `article`, `signals`, `signalCatalog`, `eventStudy`, `watchlist`, `watch`,
  `trending`, `halts`, `fundamentals`, `ticker`, `status`, `backtestReport`, `backtestRuns`, `journal`, `journalSummary`,
  `newsletterIssues`, `newsletterIssue`, `newsletterHtmlUrl`, `newsletterHtml`, `newsletterPreview`, `ingest`, plus
  `streamUrl`. Never call `fetch` from components (server components use `server-api.ts`).
- Newsletter types (`NewsletterIssue`, `NewsletterIssueSummary`, `NewsletterFiling`, ...) mirror the dict built by
  `backend/app/newsletter/service.py` `build_issue` (not a pydantic model). `SitemapTicker` (in server-api.ts) mirrors
  `GET /api/tickers/sitemap`.
- Types mirror `backend/app/schemas.py`: `Ticker` = `TickerOut`, `Signal` = `SignalOut`, `Evidence`,
  `Article` = `ArticleOut`, `ArticlePage`, `TrendingTicker`, `TickerDetail`, `Status`. `EventStudy` /
  `StudyResult` mirror the JSON written by `backend/app/research/eventstudy.py` (not a pydantic model).
  When a backend field changes, change the type here in the same commit.
- `ArticleFilters` is serialized by `query()`, which drops `undefined`, `null` and `""`. To ask for every size, send
  `size=all` (the "All sizes" option in `SIZE_FILTERS`); an empty value would let the backend default (`nano,micro,small`) apply.

## Env vars (`frontend/.env.local`)

Next reads only `frontend/.env`, `frontend/.env.local`, `frontend/.env.<mode>[.local]` and the process environment,
never the repo-root `.env`. The template is the commented frontend section at the bottom of the root `.env.example`:
copy it into `frontend/.env.local` and uncomment what you need. All optional. (There is no `frontend/.env.example`:
`frontend/.gitignore` ignores `.env*`.)

| Env var | Default | Used by |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | `api.ts` (browser); fallback for `API_URL_INTERNAL`. Inlined at build time |
| `API_URL_INTERNAL` | falls back to `NEXT_PUBLIC_API_URL` | `server-api.ts`: API origin as seen from the Next server (differs inside Docker) |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` (warning logged in production) | `SITE_URL`: canonical, og:url, JSON-LD, sitemap, robots. Must equal backend `PUBLIC_BASE_URL` |
| `PUBLIC_BASE_URL` | none | fallback for `NEXT_PUBLIC_SITE_URL` when set in a frontend env file |

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
- Feature sections are appended under their own `/* --- Name --- */` header, e.g. `/* --- Ticker SEO --- */` (summary,
  related links, `.skel*` loading skeletons) and `/* --- Newsletter (/newsletter) --- */` (`.nl*`).
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

## Content rules (legal posture)

All user-facing copy follows `docs/PRODUCT_RESEARCH.md` section 4 and `/legal/disclaimer`:
- Impersonal facts and historical statistics only. No buy/sell language, price targets or "you should".
- Label simulated results as hypothetical wherever they appear, show costs and losers, and never make earnings claims.
- When the backend logic changes (signals, entry timing, costs), update `/methodology` in the same PR.
