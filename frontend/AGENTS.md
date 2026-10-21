# frontend/: Next.js UI

Next.js 15.5 App Router, React 19, TypeScript (strict). No UI library, no state library, no CSS framework:
plain components plus `src/app/globals.css`. Path alias `@/*` -> `src/*`.
Undertow runs locally: the site is http://localhost:3000 and the API http://localhost:8000 by default, with no env
file needed. There are no accounts, pricing pages or sign-up flows; don't add any.

## Layout

```
src/app/layout.tsx          root layout: Geist fonts, <Nav/>, globals.css
src/app/page.tsx            /                landing page (server component, ISR 1 h): hero, Key findings cards read from the
                                             three study endpoints (components/home/), quick links. No buy/sell language
src/app/news/page.tsx       /news            server wrapper (metadata) around the client <NewsFeed/> (moved here from /)
src/app/signals/page.tsx    /signals         filing signals (default size "nano,micro,small")
src/app/lab/page.tsx        /lab             Edge Lab: event-study results
src/app/ticker/[symbol]/           /ticker/X  server-rendered SEO ticker page (ISR 15 min), see "Server-rendered pages"
  not-found.tsx                    404 page; catches notFound() thrown by (view)/layout.tsx
  (view)/layout.tsx                404 gate: parseSymbol + getTicker before anything streams (real HTTP 404)
  (view)/page.tsx                  server component: metadata, canonical, JSON-LD, summary paragraph, server ArticleCards
  (view)/loading.tsx               skeleton (wraps only page.tsx)
  (view)/TickerView.tsx            client part: watch toggle, 7/30/90d window, coverage bars, articles
  (view)/VaultNotes.tsx            client panel "Your notes (Obsidian)": the user's thesis notes from the vault (read-only)
  (view)/summary.ts                factual summary sentences, meta description, dateModified (pure, dated text)
  (view)/symbol.ts                 parseSymbol(): route param -> symbol or null (no second decode)
src/app/newsletter/layout.tsx      /newsletter default title + description
src/app/newsletter/page.tsx        /newsletter archive + latest issue (server component, ISR 10 min)
src/app/newsletter/[issue]/        /newsletter/2026-W41  one issue (server component, ISR 1 h); same (view)/ + not-found.tsx
                                   pattern as the ticker page (layout.tsx gate via parseIssueId, loading.tsx, page.tsx)
src/app/learn/page.tsx             /learn  lesson index + curriculum overview (static server component, no API calls)
src/app/learn/[slug]/page.tsx      /learn/<slug>  one lesson (server component, ISR 1 h, generateStaticParams from
                                   LESSON_SLUGS, dynamicParams = false so any other slug is a real 404); body from
                                   components/learn/lessons/*Lesson.tsx, live numbers via server-api getEventStudy/getBacktestReport
src/app/learn/curriculum/page.tsx  /learn/curriculum  8-week self-study path (static server component)
src/app/status/layout.tsx          /status metadata (title, description)
src/app/status/page.tsx            /status  health components, 7-day uptime, incidents, seal verification, Obsidian vault card,
                                   admin-token box (client, refresh 60 s)
src/app/sitemap.ts                 /sitemap.xml  static pages (incl. /learn, every lesson, /learn/curriculum) + /api/tickers/sitemap + archived issues (revalidate 1 h)
src/app/robots.ts                  /robots.txt   allow /, disallow /api/, points at the sitemap
src/app/research/page.tsx   /research        static research index (studies, pre-registrations, link to the paper; research.module.css)
src/app/research/paper/     /research/paper  the working paper: page.tsx reads src/content/working-paper.md at build time
                                             (force-static) and renders it with components/markdown/ (TOC from headings)
src/app/paper/page.tsx      /paper           hypothetical paper portfolio (server shell + client PaperPortfolioView)
src/app/track-record/page.tsx /track-record forward signal journal vs Edge Lab (components in src/components/track/)
src/app/backtest/page.tsx   /backtest        backtest report + live-readiness log (components in src/components/backtest/)
src/app/methodology/page.tsx /methodology  how every number is produced (keep in sync with backend logic)
src/app/legal/{disclaimer,terms,privacy}/page.tsx  DRAFT legal pages (DraftNotice until lawyer review)
src/app/trading/page.tsx    /trading         redirect("/paper") (the old "Trading (planned)" page is gone)
src/app/{signals,backtest,track-record}/layout.tsx  metadata for those client pages (a "use client" page cannot export it)
src/content/working-paper.md byte-identical copy of docs/paper/WORKING_PAPER.md (the Docker build context cannot see
                            docs/); backend/tests/test_paper_numbers.py enforces the copy. Edit the paper in docs/, then copy
src/components/             shared client components
src/lib/api.ts              the only browser API client
src/lib/server-api.ts       server-side fetch helpers (server components, generateMetadata, sitemap.ts), SITE_URL
src/lib/format.ts           formatting helpers and label maps
src/lib/learn/              Learn data + pure math (no React, no fetch): lessons.ts (registry, LESSONS, lessonPath,
                            CURRICULUM_PATH, READINGS), curriculum.ts (CURRICULUM weeks), stats.ts (seeded mulberry32 PRNG,
                            t-stats, clustered t, PSR/DSR mirroring the backend), simulations.ts (widget simulations),
                            live.ts (pull lesson numbers out of EventStudy / BacktestReport, dateLabel)
Dockerfile, .dockerignore   standalone image (next.config.ts `output: "standalone"`, node:20-alpine, `node server.js` on :3000),
                            used by the compose `web` profile
```

Most data pages are client components (`"use client"`) that fetch in `useEffect` through `api`. The exceptions are the
crawlable pages (`/`, `/research`, `/research/paper`, `/ticker/[symbol]`, `/newsletter`, `/newsletter/[issue]`, `/learn`,
`/learn/[slug]`, `/learn/curriculum`) plus `sitemap.ts`, which are server components (the ticker, newsletter and lesson pages fetch through
`src/lib/server-api.ts`; the Learn index and curriculum make no API calls). There are no API routes in Next.

## Server-rendered pages (SEO)

- `server-api.ts` helpers (`getTicker`, `getFundamentals`, `getHalts`, `getSitemapTickers`, `getNewsletterIssues`,
  `getNewsletterIssue`, `getEventStudy(study)`, `getBacktestReport`; the last two cache 1 h for the Learn lessons) return `Result<T>` (`{ok: true, data}` or `{ok: false, status, error}`, status 0 = network
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
- Learn lessons: each lesson's live numbers come from the API (1 h cache); a 404 (study not run) or API outage renders
  the lesson with an `ApiNote` instead of failing. Every live number carries a `LiveTag` (historical vs hypothetical,
  with its date). Widgets are `"use client"` islands; the simulators (`NoiseSimulator`, `ClusterSimulator`,
`SurvivorshipSimulator`) take a seed and are deterministic for it, and their output is labelled hypothetical. `repoRefs` in
  `lessons.ts` / `curriculum.ts` must point at files that exist (check with `git ls-files <path>`).
- Never convert these pages to `useEffect` client pages: crawlers would lose the content and links.

## Pages

- `/` landing page: `getEventStudy("main" | "oos" | "insider_purchases")` in parallel; `components/home/findings.ts`
  (pure, no React/fetch) turns each `Result` into a `Finding` card with Historical/Hypothetical labels and a fallback
  sentence when a study is missing (404) or the API is down (status 0). `KeyFindings.tsx` renders them. No tab is active on `/`.
- `/paper`: `PaperPortfolioView` (client) calls `api.paperPortfolio({hedge, max_concurrent})`: tiles, `EquityChart`,
  per-signal table, recent positions, assumptions; always shows the backend's hypothetical `label`. Paper-only: no
  order, broker or account UI, ever.
- `/research`: static index of the studies and pre-registrations. `/research/paper`: the working paper (see Layout).
- `/news` `NewsFeed`: filters (search debounced 300 ms, ticker, size, source, sentiment, event type),
  `before`-cursor pagination ("Load older"), live SSE inserts, `Sidebar` (trending tickers, source status,
  "ingest now").
- `/signals`: `api.signals()` with size / min_severity / signal (from `api.signalCatalog()`) / watchlist
  filters, `WatchlistPanel`, legend. SSE `article` events trigger a reload debounced by 3 s.
- `/lab`: `api.studies()` + `api.eventStudy(name)` per study; a study selector (`main` = in-sample live evidence,
  `oos` = pre-registered out-of-sample 2020-23, `insider_purchases` = Form 4 study); the `ResearchRunPanel` uses the
  selected study's kind (`event_study`, `event_study_oos`, `insider_study`). Tiles, "what survived", per-bucket `DivergingChart` of
  `mean_net` with a 5d/20d toggle, coverage/survivorship table, full results table (incl. clustered t when present),
  caveats; for OOS the `ConfirmatoryBlock` verdicts (from `components/learn/`) and an in-sample vs OOS comparison table.
  404 -> "No study yet" message. An older API without `/api/research/studies` falls back to the main study only.
- `/learn`, `/learn/[slug]`, `/learn/curriculum`: see "Server-rendered pages". Six lessons (slug -> body in
  `components/learn/lessons/`, mapped by `BODIES` in `app/learn/[slug]/page.tsx`): `event-study` -> `EventStudyLesson.tsx`,
  `baselines` -> `BaselinesLesson.tsx`, `multiple-testing` -> `MultipleTestingLesson.tsx`, `clustered-errors` ->
  `ClusteredErrorsLesson.tsx`, `survivorship-bias` -> `SurvivorshipLesson.tsx`, `sharpe-dsr-backtest-pitfalls` ->
  `SharpeDsrLesson.tsx`. A new lesson needs an entry in `LESSONS` (lessons.ts) and in `BODIES`; the sitemap picks it up.
- `/status`: `api.healthDetails()` + `api.healthHistory(7)` (refresh every 60 s), `api.journalVerify()`, `api.status()`
  for `admin`; an admin-token box that stores the token in session storage (`setAdminToken`) for protected servers.
  `VaultCard` (Obsidian vault): `api.vaultStatus()` on the same 60 s refresh shows on/off, the API's vault path, last
  export (relative time), created/updated/unchanged/errors, per-folder counts and waiting conflict files
  (`Undertow/_conflicts/`); **Export now** calls `api.vaultExport()` (admin; 401/403/429 show the admin message, 409 =
  "already running or disabled"), disabled while running or when `VAULT_ENABLED` is off. Styles in `status.module.css`
  (`vaultList`, `vaultPath`, `vaultFolders`, `vaultActions`).
- `/newsletter` also renders `SubscribeForm` (client island, anchor `#subscribe`); the page stays a server component.
- `/ticker/[symbol]`: server-fetched ticker (90 days), fundamentals and halts; factual summary paragraph, then
  `TickerView` (watchlist re-checked in the browser, window switch re-fetches via `api.ticker`), `DilutionPanel` (server
  data, or client fetch if the server call failed with non-404, omitted without a CIK or on 404), `HaltsPanel`,
  `VaultNotes`, coverage bars, articles, related links. `VaultNotes` (client, after hydration so the cached server HTML
  never contains personal notes) calls `api.vaultNotes(symbol)` and lists title, updated date (date-only values
  formatted in UTC), vault path and excerpt **as plain text** (never Markdown/HTML rendering). Empty state: a copyable
  `type: thesis` + `ticker:` frontmatter example; `enabled: false` -> "Vault integration is off"; errors -> a muted
  "unavailable" line. Inline styles from the globals.css tokens (no CSS module in that folder).
- `/newsletter`, `/newsletter/[issue]`: `NewsletterWorkspace` = `ArchiveList` sidebar + export toolbar (Copy Markdown,
  Download HTML, Open email version) + `IssueView`. "Preview this week so far" calls `api.newsletterPreview()` (POST,
  never archived). If the server could not reach the API, the workspace retries from the browser.
- `/backtest`: `api.backtestReport()` + `api.backtestRuns()`. Verdict and key finding first, then A/B tiles,
  friction waterfall, borrow fees, equity/drawdown charts (inline SVG `TimeChart`), readiness checklist,
  real-money projection, stress, robustness, trade log (CSV export), run log, assumptions. Types `BacktestReport`
  etc. mirror the JSON from `backend/app/backtest/report.py`.
- `/track-record`: `api.journal()` + `api.journalSummary()`; status tiles, `SealPanel` (hash-chain head from
  `api.journalChain()`, verification from `api.journalVerify()`, how to recompute a day), live-vs-expected table ("too early" under
  5 results), nano-offering spotlight with a running-mean chart, filterable journal table with CSV.
- `/ticker/[symbol]` also renders `DilutionPanel` (`initialData` or `api.fundamentals()`): runway, cash, 1-year share change, offering history.
- Charts measure their container width. In a hidden/zero-width browser pane they render no SVG; that is expected, not a bug.
- `/trading` redirects to `/paper`. Anything trading-related stays hypothetical and paper-only; agents never place orders.

## Components

| File | Role |
|---|---|
| `Nav.tsx` | Header tabs from `TABS` (News `/news`, Signals, Track record, Paper `/paper`, Newsletter, Edge Lab, Backtest, Learn, Research); `isActive()`: `/ticker/*` highlights News, `/research/paper` highlights Research, `/` highlights none. Add new pages here |
| `home/` | Landing page: `findings.ts` (pure Finding builders + `pct`), `KeyFindings.tsx`, `home.module.css` |
| `markdown/Markdown.tsx` (+ `.module.css`) | Tiny server-side Markdown renderer for docs we own (`parseMarkdown`, `headings`, `plainText`): headings with ids, lists, GFM tables, code, quotes, links (http(s)/relative only) |
| `portfolio/` | `/paper`: `PaperPortfolioView.tsx` (client), `EquityChart.tsx`, `portfolio.module.css` |
| `NewsFeed.tsx` | News tab body; owns the SSE subscription for `/`. Has its own `EVENT_TYPES` list for the filter |
| `ArticleCard.tsx` | One article/filing: badges, sentiment, signals, AI flags, tickers with size, `EvidenceLine`; forward-test signals get a "Forward test of pre-registered finding" badge and an "(in-sample, hypothetical)" evidence line |
| `Sidebar.tsx` | Trending tickers (`api.trending(hours)`), `api.status()`, manual `api.ingest()` |
| `Footer.tsx` | Site-wide footer (client component, in layout.tsx): disclaimer line, Methodology / Subscribe (`/newsletter#subscribe`) / Status / legal links; also shows a dismissible notice for any unhandled admin `ApiError` (401/403/429) with a link to `/status` |
| `SubscribeForm.tsx` (+ `.module.css`) | Email signup (`api.subscribe(email, daily)`) on `/newsletter`; generic success message (no enumeration), 503 -> "not set up yet", 422 -> invalid email |
| `track/SealPanel.tsx` (+ `.module.css`) | Track-record hash-chain head, verify result, the raw day export URL (`/api/journal/chain/{day}`) and a Python snippet to recompute a day's hash |
| `learn/` | Learn UI: `LessonLayout` (shared lesson frame, JSON-LD, prev/next), `lessons/*Lesson.tsx` (async server bodies), `parts.tsx` (`LiveTag`, `ApiNote`, `RepoRefs`, `Readings`, `Disclaimer`, `VerdictBadge`, `fmtT`; no hooks, also used by `/lab`), `ConfirmatoryBlock.tsx` (OOS verdicts, also used by `/lab`), client widgets `EventStudyExplorer`, `NoiseSimulator`, `ClusterSimulator`, `SurvivorshipSimulator`, `DsrCalculator`, plus `charts.tsx`, `controls.tsx`, `learn.module.css` |
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
  `cache: "no-store"` and throw an `ApiError` (`status`, `detail`, `admin`) whose message starts with the status
  (`"404 ..."`), so pages can keep checking `startsWith("404")`.
- Writes go through `send(path, method, { admin?, body? })`. `admin: true` attaches `Authorization: Bearer <token>`
  from `getAdminToken()` (session storage key `undertow.researchAdminToken`, shared by `/status` and
  `ResearchRunPanel`; `setAdminToken` stores/clears it) and maps 401/403 to the `ADMIN_TOKEN_REQUIRED` /
  `CHANGES_DISABLED` messages; 429 becomes "Too many requests. Try again in N seconds." `isAdminApiError(e)` is true for
  admin 401/403/429. Admin calls: `startResearch`, `watch` (PUT/DELETE), `ingest`, `vaultExport`. Public writes (`subscribe`,
  `newsletterPreview`) send no token. (`ResearchRequestError` was replaced by `ApiError`.)
- `api.*` methods: `researchJobs`, `startResearch`, `articles`, `article`, `signals`, `signalCatalog`,
  `eventStudy(study = "main")`, `studies`, `watchlist`, `watch`, `trending`, `halts`, `fundamentals`, `ticker`, `status`,
  `backtestReport`, `backtestRuns`, `journal`, `journalSummary`, `journalChain`, `journalChainDay`, `journalVerify`,
  `healthDetails`, `healthHistory(days)`, `subscribe(email, daily)`, `newsletterIssues`, `newsletterIssue`,
  `newsletterHtmlUrl`, `newsletterHtml`, `newsletterPreview`, `ingest`, `paperPortfolio(params)`, `vaultStatus`,
  `vaultNotes(ticker)`, `vaultExport` (POST, 120 s timeout), plus `streamUrl`. Never call `fetch` from
  components (server components use `server-api.ts`).
- Batch 2026-10-19 types: `StudyName`, `StudyInfo`, `ConfirmatoryResult` (+ `EventStudy.confirmatory`,
  `confirmatory_testing`, `preregistration`, `config.study`, `StudyResult.t_stat_clustered` / `t_vs_baseline_clustered` /
  `clusters`), `ResearchJobKind` (`backtest | event_study | event_study_oos | insider_study`), `AdminStatus`
  (`Status.admin`), `HealthState`, `HealthComponent`, `HealthDetails`, `HealthIncident`, `HealthHistory`, `ChainLine`,
  `JournalChain`, `ChainDay`, `ChainVerify`, and `seal` on the newsletter issue's `track_record`.
- v1.0 types (all new fields optional, so older APIs still type-check): `Signal.forward_test`, `Evidence.study` /
  `forward_test` / `t_stat_clustered` / `companies`, `Article.forward_test`, journal rows' `evaluation_horizon` /
  `forward_test_label`, and `PaperPortfolio` (`PaperAssumptions`, `PaperEquityPoint`, `PaperTotals`, `PaperSignalRow`,
  `PaperPosition`, `PaperPortfolioParams`) mirroring `PaperPortfolioOut`.
- Vault types: `VaultStatus` (= `VaultStatusOut`), `VaultExportResult` (= `VaultExportResultOut`), `VaultNotes`
  (= `VaultNotesOut`), `VaultNote` (= `VaultNoteOut`; `excerpt` is plain text).
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
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` (unset is the normal local case) | `SITE_URL`: canonical, og:url, JSON-LD, sitemap, robots. The **site** origin, not the API. Must equal backend `PUBLIC_BASE_URL`. While it is a loopback origin (`isLocalSiteUrl()`), `robots.txt` disallows everything |
| `PUBLIC_BASE_URL` | none | fallback for `NEXT_PUBLIC_SITE_URL` when set in a frontend env file |

## Container image (`Dockerfile`) and the compose `web` profile

`docker compose --profile web up -d --build` (or `scripts/start.ps1`) builds this image as the `web` service with build
args `NEXT_PUBLIC_API_URL=http://localhost:8000` and `NEXT_PUBLIC_SITE_URL=http://localhost:3000`, sets
`API_URL_INTERNAL=http://api:8000` and publishes `127.0.0.1:3000`. A plain `docker compose up` skips it, so it never
collides with `npm run dev` on :3000 (don't run both). `docker-compose.prod.yml` is optional, for later.

`next.config.ts` sets `output: "standalone"`. The multi-stage `Dockerfile` (node:20-alpine: `npm ci`, `npm run build`,
non-root runner, `node server.js` on port 3000) takes `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_SITE_URL` as **build args**
(inlined into the bundle: rebuild to change them); `API_URL_INTERNAL` is read at runtime (`http://api:8000` in
the compose `web` service). `.dockerignore` excludes `node_modules`, `.next` and `.env*`. CI builds the
image but never pushes it.

## SSE

`ResearchRunPanel` provides the launch/rerun controls on Backtest and Edge Lab (on Edge Lab, for the selected study's kind), including
empty states. On a protected server it asks for the admin token and stores it with `setAdminToken` (shared with `/status`).
It polls `api.researchJobs()` for the shared job slot, prevents duplicate launches, and refreshes page
results after completion. Job state belongs to the backend so navigation does not stop work.
Failures leave prior results visible and expose a retry action. Research settings remain fixed.

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
  related links, `.skel*` loading skeletons), `/* --- Newsletter (/newsletter) --- */` (`.nl*`) and `/* --- Learn --- */`
  (`--learn-hist`, `--learn-hypo` label colors, dark default + light override). New components prefer CSS modules
  (`learn.module.css`, `SubscribeForm.module.css`, `SealPanel.module.css`, `status.module.css`) over more globals.
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
- No pricing, plans, sign-up or "Pro" copy: Undertow is free and local-only. Don't describe it as a hosted or public service.
- **Markdown rendering:** render Markdown only through `components/markdown/Markdown.tsx`, which builds React elements.
  Never use `dangerouslySetInnerHTML` for Markdown or any document text, and never add an HTML-string Markdown library (the escaped JSON-LD `<script>` tags are the only `dangerouslySetInnerHTML` use).
- When the backend logic changes (signals, entry timing, costs), update `/methodology` in the same PR.
