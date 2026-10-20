# Undertow: agent guide (start here)

Undertow is a personal, **locally run** small-cap SEC-filing research platform (v1.0): live SEC filing signals for
companies under $2B public float, each shown next to an event-study result on how similar stocks moved afterwards.
It also has a landing page with the key findings, a live market news feed (EDGAR, RSS, optional Alpaca/Benzinga) with
optional Claude enrichment, a hash-sealed track record, a live forward test of the insider-cluster finding, a
hypothetical paper portfolio, a working paper, a weekly newsletter with optional email delivery, a Learn section and a
`/status` page. It runs on the owner's machine via Docker (ports on 127.0.0.1): no paid tier, no accounts, no hosting.
Research and education only; it never places orders.

Read this file, then only the AGENTS.md of the folder you are working in.

## Multi-agent process (read before orchestrating)

- **Repo graph:** [docs/agent-graph.json](docs/agent-graph.json). Modules with their paths, AGENTS.md, dependencies, tests, hotspot files and shared resources.
- **Process graph:** [docs/AGENT_PROCESS.md](docs/AGENT_PROCESS.md) and `.claude/workflows/feature-graph.js`. The steps are Plan, then ownership edges and waves, then Build, then 2-lens Review with a fix loop, then an exclusive Verify, then a Critic.
- Builders run backend tests with `bash scripts/pytest.sh <tests>`, which is safe in parallel. Only the Verify step runs `docker compose build` or `next build`.

## Directory map

| Path | Purpose | Guide |
|---|---|---|
| `backend/` | FastAPI app, DB, tests, Dockerfile | [backend/AGENTS.md](backend/AGENTS.md) |
| `backend/app/sources/` | One adapter per data source, each returns `RawArticle` | [sources/AGENTS.md](backend/app/sources/AGENTS.md) |
| `backend/app/pipeline/` | Ingest cycle: dedupe, ticker tagging, company sizes, signal taxonomy (`ALL_SIGNALS` + `FORWARD_TEST_SIGNALS`), LLM enrichment, SSE, `store_and_publish` | [pipeline/AGENTS.md](backend/app/pipeline/AGENTS.md) |
| `backend/app/research/` | Event study (`eventstudy.py`, `StudyDesign`), pre-registered out-of-sample study (`oos.py`), offline replay manifests (`snapshot.py`), Yahoo price loader (`prices.py`), working-paper number check (`paper_numbers.py`) | [research/AGENTS.md](backend/app/research/AGENTS.md) |
| `backend/app/insiders/` | Separate pre-registered Form 4 insider-purchase study (SEC insider data sets, Form 4 XML parser) and the live insider-cluster forward test (`live.py`, `settings.py`, `evidence.py`) | [insiders/AGENTS.md](backend/app/insiders/AGENTS.md) |
| `backend/app/backtest/` | Portfolio backtester, run log, readiness gates, IBKR borrow archiver | [backtest/AGENTS.md](backend/app/backtest/AGENTS.md) |
| `backend/app/journal/` | Forward signal journal: live track record vs study expectations, evaluation horizons, tamper-evident daily hash chain (`digest.py`) | [journal/AGENTS.md](backend/app/journal/AGENTS.md) |
| `backend/app/paper/` | Hypothetical paper portfolio simulated from the journal (`GET /api/paper-portfolio`). No execution code, ever | [paper/AGENTS.md](backend/app/paper/AGENTS.md) |
| `backend/app/alerts/` | 30-second EDGAR polling + Discord alerts (optional) with latency log | [alerts/AGENTS.md](backend/app/alerts/AGENTS.md) |
| `backend/app/fundamentals/` | Cash runway and dilution history from SEC XBRL + filings | [fundamentals/AGENTS.md](backend/app/fundamentals/AGENTS.md) |
| `backend/app/newsletter/` | Weekly "Small-Cap Filing Radar": build, Markdown/HTML render, immutable archive, CLI | [newsletter/AGENTS.md](backend/app/newsletter/AGENTS.md) |
| `backend/app/delivery/` | Email delivery (off unless SMTP is configured): double opt-in list, newsletter fan-out, daily digest, `/api/subscribe` router | [delivery/AGENTS.md](backend/app/delivery/AGENTS.md) |
| `backend/app/security.py`, `backend/app/health.py` | Admin policy for mutating endpoints + per-client rate limiter; deep health check + uptime history | covered in backend/AGENTS.md |
| `backend/tests/` | pytest suite (in-memory SQLite, no network); `fixtures/form4/` (insider study) and `fixtures/form4_live/` (live forward test) | covered in backend/AGENTS.md |
| `frontend/` | Next.js 15 App Router UI; `Dockerfile` = standalone image used by the compose `web` profile | [frontend/AGENTS.md](frontend/AGENTS.md) |
| `frontend/src/app/page.tsx`, `frontend/src/components/home/` | Landing page `/` with the key findings read from the study endpoints | frontend/AGENTS.md |
| `frontend/src/app/news/` | `/news`: the live news feed (moved from `/`) | frontend/AGENTS.md |
| `frontend/src/app/paper/`, `frontend/src/components/portfolio/` | `/paper`: hypothetical paper portfolio (`/trading` redirects here) | frontend/AGENTS.md |
| `frontend/src/content/`, `frontend/src/components/markdown/` | `working-paper.md` (byte-identical copy of the paper) and the safe Markdown renderer behind `/research/paper` | frontend/AGENTS.md |
| `docs/` | Feasibility and product research (background), published results, the working paper, batch plans, agent graph + process | [docs/AGENTS.md](docs/AGENTS.md) |
| `docs/paper/` | `WORKING_PAPER.md`: write-up of all three studies and the backtest; numbers checked by `paper_numbers.py` | [research/AGENTS.md](backend/app/research/AGENTS.md) |
| `scripts/start.ps1` | Windows one-command start: creates `.env` from `.env.example` if missing, `docker compose --profile web up -d --build`, prints the URLs (`-NoWeb` skips the UI container) | its header comment |
| `scripts/pytest.sh` | Backend tests against mounted source in the `undertow-api-test` image (`backend/` at `/app`, repo read-only at `/repo`; no image rebuild, parallel-safe) | [docs/AGENT_PROCESS.md](docs/AGENT_PROCESS.md) |
| `scripts/reproduce.sh`, `Makefile` | Offline replay of the in-sample / OOS / insider study and canonical compare (`make reproduce`, `make reproduce-oos`, `make reproduce-insiders`); also `make test`, `make test-file F=...`, `make snapshot` | [research/AGENTS.md](backend/app/research/AGENTS.md) |
| `.github/workflows/ci.yml` | CI on every push/PR: backend pytest, frontend tsc + lint + build, both Docker images built (never pushed). Needs no secrets | |
| `.claude/workflows/feature-graph.js` | Multi-agent Plan/Build/Review/Verify/Critic workflow | [docs/AGENT_PROCESS.md](docs/AGENT_PROCESS.md) |
| `docker-compose.yml` | Local stack: `db` (pgvector/pgvector:pg17) + `api`, and `web` (frontend image) behind the `web` profile; all bound to 127.0.0.1 | its header comment |
| `docker-compose.prod.yml` | Optional, for later; not used by the local-only setup. Hardened template (needs an env file outside git with `POSTGRES_PASSWORD` and `ADMIN_TOKEN`). Never deploy publicly with Yahoo prices | its header comment |
| `.env.example` | Every optional env var with comments. Backend section: copy to `.env` (git-ignored), read by compose and the backend. Commented frontend section at the bottom: template for `frontend/.env.local` (Next never reads the root file) | |
| `.claude/launch.json` | Preview config: frontend dev server on :3000 | |

## Run everything

```bash
# Windows, one command (creates .env if missing, starts db + api + web, prints URLs):
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
# Same by hand:
cp .env.example .env                        # optional (Windows: copy); the app runs on free sources without keys
docker compose --profile web up -d --build  # Postgres :5432 + API :8000 + UI :3000 (web container)
# Dev mode instead (hot reload): no web profile, run Next yourself
docker compose up -d --build                # Postgres + API only
npm --prefix frontend install               # first time only
npm --prefix frontend run dev               # UI on :3000 (API base: NEXT_PUBLIC_API_URL, default http://localhost:8000)
```

Do not run the `web` profile and `npm run dev` together: both want port 3000. Open http://localhost:3000; API health at
http://localhost:8000/api/health. Stop with `docker compose --profile web down` (volumes keep the data).

Python is not installed on the host. Run all Python through the `api` container:

```bash
docker compose build api                                       # code is COPYed into the image: rebuild after edits
docker compose run --rm api pytest -q                          # backend tests (agents: bash scripts/pytest.sh instead, no rebuild)
docker compose run --rm api python -m app.research.eventstudy  # event study (~15 min first run, cached after)
docker compose restart api                                     # API reloads event_study.json and forward-test evidence at startup
docker compose run --rm api python -m app.newsletter.build     # newsletter: last completed week (--week-end, --force, --preview)
docker compose run --rm api python -m app.research.oos          # pre-registered out-of-sample study -> event_study_oos.json
docker compose run --rm api python -m app.insiders.study       # Form 4 insider study -> event_study_insider_purchases.json (~1-2 h first run)
docker compose run --rm api python -m app.journal.digest verify # journal hash chain (seal | verify | export YYYY-MM-DD)
make reproduce                                                 # offline replay of the in-sample study vs docs/results (= bash scripts/reproduce.sh main)
bash scripts/pytest.sh tests/test_paper_numbers.py             # working paper numbers vs docs/results (needs the /repo mount)
```

## Env vars

Backend settings live in `backend/app/config.py` (table in [backend/AGENTS.md](backend/AGENTS.md)), documented in `.env.example`.
The frontend reads only `frontend/.env*` (table in [frontend/AGENTS.md](frontend/AGENTS.md)), documented in the commented frontend section of `.env.example` (template for `frontend/.env.local`).
Every default is local and needs no change.

- **Two origins, do not mix them up.** The **site origin** (the Next.js frontend) is `http://localhost:3000`; the
  **API origin** is `http://localhost:8000`. `PUBLIC_BASE_URL` (root `.env`, newsletter/email links, and the admin
  policy's localhost check) is the *site* origin, never the API. `NEXT_PUBLIC_SITE_URL` (`frontend/.env.local`;
  canonical URLs, sitemap, robots) defaults to `http://localhost:3000` and must equal `PUBLIC_BASE_URL`.
  `NEXT_PUBLIC_API_URL` defaults to `http://localhost:8000`. The compose `web` service bakes those two `NEXT_PUBLIC_*`
  defaults in as build args and sets `API_URL_INTERNAL=http://api:8000` for server-side fetches.
- `INSIDER_LIVE_ENABLED` (default `true`; `app/insiders/settings.py` `InsiderLiveSettings`, not yet in
  `app.config.Settings`): the live insider-cluster forward test runs in the fast EDGAR poller when this and
  `EDGAR_ENABLED` are true. `false` stops all Form 4 requests.
- Optional integrations, all off while unset: Alpaca news (`ALPACA_API_KEY_ID` + `ALPACA_API_SECRET_KEY`), Claude
  enrichment (`ANTHROPIC_API_KEY`), Discord alerts (`DISCORD_WEBHOOK_URL`), email delivery (`DeliverySettings` in
  `app/delivery/settings.py`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`,
  `SMTP_TIMEOUT_SECONDS`, `EMAIL_FROM`, `EMAIL_REPLY_TO`, `EMAIL_POSTAL_ADDRESS`, `EMAIL_DAILY_DIGEST_HOUR_ET`,
  `EMAIL_MAX_PER_RUN`, `EMAIL_LINK_BASE_URL`, `EMAIL_TOKEN_SECRET`; on only when `SMTP_HOST`, `EMAIL_FROM` and
  `EMAIL_POSTAL_ADDRESS` are all set).
- Admin protection (`AdminSettings` in `app/config.py`, policy in `app/security.py`): `ADMIN_TOKEN` (the old name
  `RESEARCH_ADMIN_TOKEN` is still accepted), `RESEARCH_JOBS_ENABLED`, `MUTATIONS_ENABLED`. Without a token or flag,
  mutations work only while `PUBLIC_BASE_URL` is localhost (the local default).
- Rate limits: `RATE_LIMIT_PER_MINUTE` (120), `RATE_LIMIT_WRITE_PER_MINUTE` (10), `TRUST_PROXY_HEADERS` (false; not
  needed locally).
- Not settings: `POSTGRES_PASSWORD` (only for the optional prod compose env file), `GIT_SHA` (code version in study
  manifests), `REPRO_BUILD=1` (`scripts/reproduce.sh` rebuilds the api image first), `UNDERTOW_REPO_ROOT` (repo root
  for `paper_numbers.find_repo_root`, else `/repo`).

## Conventions (non-negotiable)

- **Local only.** Undertow is not deployed anywhere and has no paid tier, accounts or pricing. Do not add Stripe,
  sign-up, entitlement or hosting code. `docker-compose.prod.yml` is optional, for later.
- **SEC User-Agent comes from config** (`settings.sec_user_agent`, env `SEC_USER_AGENT`). Pass it through;
  never hard-code a personal email or any contact string in code, tests or docs.
- **Research prices are Yahoo, personal use only** (`backend/app/research/prices.py`). Throttled, cached,
  never redistributed or served raw by the API; the UI shows only aggregate statistics. **No public deployment
  with Yahoo data**: anything public needs a licensed feed first.
- **Agents never place orders.** No broker order code paths (the paper portfolio is a calculation;
  `test_paper_portfolio.py` greps `app/paper/` for execution words). Alpaca keys are paper keys used for news only.
- **No secrets in git.** Keys live in `.env` (ignored by `.gitignore`). Never commit live keys or `backend/data/`.
- Event-study design changes happen before looking at results, never after (see research/AGENTS.md). The OOS and
  insider studies are pre-registered (`backend/app/research/PREREGISTRATION_OOS.md`, `backend/app/insiders/PREREGISTRATION.md`);
  their CLIs never write `event_study.json` (the live evidence).
- **Forward-test signals live outside `ALL_SIGNALS`**, in `FORWARD_TEST_SIGNALS` (`pipeline/signals.py`), so the main
  study's taxonomy and Bonferroni count never change. Resolve stored signal codes with `signal_def()`, never
  `ALL_SIGNALS[code]`; forward-test evidence comes from its own study file (`insiders/evidence.py`), never `event_study.json`.
- **Paper numbers are checked.** Change a number in `docs/paper/WORKING_PAPER.md` -> update `HEADLINE` in
  `paper_numbers.py` and copy the paper byte-identically to `frontend/src/content/working-paper.md`.
- **Every mutating endpoint goes through the admin policy** (`app/security.py`); never add an unprotected write
  except deliberate public ones (subscribe, newsletter preview), which the write-tier rate limit covers.
- **Email:** only double opt-in via `POST /api/subscribe`; never bulk-insert subscribers or send from tests (delivery/AGENTS.md).
- UI shows headlines and links out; never republish full article text. Content rules (no buy/sell language,
  label hypothetical results) are in frontend/AGENTS.md and apply to docs too.

## How to add...

**A data source**
1. `backend/app/sources/<name>.py`: class with `name: str` and `fetch() -> list[RawArticle]` (contract in sources/AGENTS.md).
2. Register it in `build_sources()` in `backend/app/pipeline/ingest.py` (this also makes it appear in `/api/status`).
3. Settings in `backend/app/config.py` (+ an `*_enabled` property if optional) and a commented line in `.env.example`.
4. If it introduces a new `source` value: `SOURCE_LABELS` in `frontend/src/lib/format.ts` and the source `<select>` in `frontend/src/components/NewsFeed.tsx`.
5. Parser test in `backend/tests/` with a canned payload (no network).

**A filing signal**
1. Add a `SignalDef` to `ITEM_SIGNALS` (8-K item) or `FORM_SIGNALS` (form) in `backend/app/pipeline/signals.py`.
2. New form: also add it to `EVENT_FORMS` (signals.py) and `FORM_EVENTS` (`backend/app/sources/edgar.py`).
3. Live alerts, `/api/signals/catalog` and the event study pick it up via `signals_for_filing()`. Adding a signal
   changes the Bonferroni test count, so it is a design change: decide it, then rerun the study.
4. A live forward test of a finding from a separate pre-registered study goes in `FORWARD_TEST_SIGNALS` instead
   (with an `EVALUATION_HORIZONS` entry in `journal/service.py` if it is not judged at 20 days).

**A page**
1. `frontend/src/app/<route>/page.tsx` (`"use client"` if it uses hooks). A page that must be crawlable is a server
   component that fetches through `frontend/src/lib/server-api.ts` (pattern: `app/ticker/[symbol]/(view)/`), and gets an entry in `app/sitemap.ts`.
2. Add a tab to `TABS` in `frontend/src/components/Nav.tsx`.
3. New endpoint: route in `backend/app/main.py`, response model in `backend/app/schemas.py`, mirrored type +
   method in `frontend/src/lib/api.ts`. A mutating endpoint gets `dependencies=[Depends(require_admin("mutations"))]`
   in main.py and the browser calls it through `send(..., { admin: true })` in api.ts; public writes are only rate-limited.

## Where to start for task X

| Task | Start in |
|---|---|
| New API endpoint or filter | `backend/app/main.py`, `backend/app/schemas.py`, `frontend/src/lib/api.ts` |
| New DB column | `backend/app/models.py` (must be nullable; see stopgap migration in backend/AGENTS.md) |
| Env var / setting | `backend/app/config.py`, `.env.example` |
| Local start, compose, Windows | `scripts/start.ps1`, `docker-compose.yml` (`web` profile), `frontend/Dockerfile` |
| Landing page and key findings | `frontend/src/app/page.tsx`, `frontend/src/components/home/` (`findings.ts`, `KeyFindings.tsx`) |
| Feed is missing or duplicating stories | `backend/app/pipeline/dedupe.py`, `ingest.py` (`is_duplicate`) |
| Wrong or missing tickers | `backend/app/pipeline/tickers.py`, `sources/edgar.py` (`tickers_for_cik`) |
| Wrong size bucket | `backend/app/pipeline/companies.py` (`BUCKETS`, `load_latest_floats`) |
| EDGAR parsing / 13D handling | `backend/app/sources/edgar.py` (`parse_entry`) |
| LLM summary, sentiment, flags, model choice | `backend/app/pipeline/enrich.py` |
| Live updates in the UI | `backend/app/pipeline/events.py`, `/api/stream` in `main.py`, `NewsFeed.tsx` |
| Event-study method or results | `backend/app/research/eventstudy.py`, `docs/results/`; other studies are served via `STUDY_FILES` in `main.py` (`/api/research/event-study?study=`) |
| Evidence line on signal cards | `load_study()` / `load_forward_evidence()` / `to_out()` in `main.py`, `ArticleCard.tsx` |
| Live insider forward test (Form 4 poller, cluster signal) | `backend/app/insiders/live.py`, `settings.py`, `evidence.py`; `_poll_form4` in `pipeline/ingest.py`; `FORWARD_TEST_SIGNALS` in `pipeline/signals.py`; `EVALUATION_HORIZONS` in `journal/service.py` |
| Paper portfolio (hypothetical) | `backend/app/paper/service.py`, `/api/paper-portfolio` in `main.py`, `frontend/src/app/paper/`, `frontend/src/components/portfolio/` |
| Working paper and its numbers | `docs/paper/WORKING_PAPER.md`, `backend/app/research/paper_numbers.py` (`HEADLINE`), `backend/tests/test_paper_numbers.py`, `frontend/src/content/working-paper.md`, `frontend/src/app/research/paper/`, `frontend/src/components/markdown/` |
| Edge Lab charts | `frontend/src/app/lab/page.tsx`, `--div-*` tokens in `globals.css` |
| Strategy backtests | `backend/app/backtest/` (its own AGENTS.md) |
| Weekly newsletter content or schedule | `backend/app/newsletter/service.py`, `newsletter_cycle()` in `main.py`, `frontend/src/components/newsletter/` |
| Ticker page text, metadata, sitemap, robots | `frontend/src/app/ticker/[symbol]/(view)/` (`summary.ts`), `app/sitemap.ts`, `app/robots.ts` (disallows all on a localhost site origin), `/api/tickers/sitemap` in `main.py` |
| Admin token, 401/403 on writes, 429 rate limits | `backend/app/security.py`, `require_admin` in `main.py`, `send()` / `ApiError` in `frontend/src/lib/api.ts`, `/status` |
| Health, uptime, Status page | `backend/app/health.py`, `/api/health/*` in `main.py`, `frontend/src/app/status/` |
| Email list, newsletter emails, daily digest | `backend/app/delivery/` (its own AGENTS.md), `newsletter_cycle()` / `digest_cycle()` in `main.py`, `SubscribeForm.tsx` |
| Track-record seal (hash chain) | `backend/app/journal/digest.py`, `seal_cycle()` and `/api/journal/chain`, `/api/journal/verify` in `main.py`, `components/track/SealPanel.tsx` |
| Out-of-sample study, offline replay | `backend/app/research/oos.py`, `snapshot.py`, `scripts/reproduce.sh` |
| Insider-purchase (Form 4) study | `backend/app/insiders/` (its own AGENTS.md and PREREGISTRATION.md) |
| Learn lessons and simulators | `frontend/src/app/learn/`, `frontend/src/components/learn/`, `frontend/src/lib/learn/` |
| CI; server deploy (optional, for later) | `.github/workflows/ci.yml`; `docker-compose.prod.yml`, `frontend/Dockerfile` |
| Feasibility / product docs (background) | `docs/` |
