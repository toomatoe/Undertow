# QuantDesk: agent guide (start here)

QuantDesk is small-cap event intelligence: live SEC filing signals for companies under $2B public float,
each shown next to an event-study result on how similar stocks moved afterwards.
It also has a live market news feed (EDGAR, RSS, optional Alpaca/Benzinga) with optional Claude enrichment,
a weekly newsletter with optional email delivery, a hash-sealed public track record, a Learn section and a `/status` page.
Research and education only; it does not trade.

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
| `backend/app/pipeline/` | Ingest cycle: dedupe, ticker tagging, company sizes, signal taxonomy, LLM enrichment, SSE | [pipeline/AGENTS.md](backend/app/pipeline/AGENTS.md) |
| `backend/app/research/` | Event study (`eventstudy.py`, `StudyDesign`), pre-registered out-of-sample study (`oos.py`), offline replay manifests (`snapshot.py`), Yahoo price loader (`prices.py`) | [research/AGENTS.md](backend/app/research/AGENTS.md) |
| `backend/app/insiders/` | Separate pre-registered Form 4 insider-purchase event study (SEC insider data sets, Form 4 XML parser) | [insiders/AGENTS.md](backend/app/insiders/AGENTS.md) |
| `backend/app/backtest/` | Portfolio backtester, run log, readiness gates, IBKR borrow archiver | [backtest/AGENTS.md](backend/app/backtest/AGENTS.md) |
| `backend/app/journal/` | Forward signal journal: live track record vs Edge Lab expectations, tamper-evident daily hash chain (`digest.py`) | [journal/AGENTS.md](backend/app/journal/AGENTS.md) |
| `backend/app/alerts/` | 30-second EDGAR polling + Discord alerts with latency log | [alerts/AGENTS.md](backend/app/alerts/AGENTS.md) |
| `backend/app/fundamentals/` | Cash runway and dilution history from SEC XBRL + filings | [fundamentals/AGENTS.md](backend/app/fundamentals/AGENTS.md) |
| `backend/app/newsletter/` | Weekly "Small-Cap Filing Radar": build, Markdown/HTML render, immutable archive, CLI | [newsletter/AGENTS.md](backend/app/newsletter/AGENTS.md) |
| `backend/app/delivery/` | Email delivery (off unless SMTP is configured): double opt-in list, newsletter fan-out, daily digest, `/api/subscribe` router | [delivery/AGENTS.md](backend/app/delivery/AGENTS.md) |
| `backend/app/security.py`, `backend/app/health.py` | Admin policy for mutating endpoints + per-client rate limiter; deep health check + uptime history | covered in backend/AGENTS.md |
| `backend/tests/` | pytest suite (in-memory SQLite, no network); `fixtures/form4/` holds the insider-study fixtures | covered in backend/AGENTS.md |
| `frontend/` | Next.js 15 App Router UI (server-rendered SEO pages for tickers, newsletter issues and Learn lessons, sitemap, robots, `/status`); `Dockerfile` = standalone production image | [frontend/AGENTS.md](frontend/AGENTS.md) |
| `docs/` | Feasibility research, product research, published event-study results, batch plans, agent graph + process | [docs/AGENTS.md](docs/AGENTS.md) |
| `scripts/pytest.sh` | Backend tests against mounted source in the `quantdesk-api-test` image (no image rebuild, parallel-safe) | [docs/AGENT_PROCESS.md](docs/AGENT_PROCESS.md) |
| `scripts/reproduce.sh`, `Makefile` | Offline replay of the in-sample / OOS / insider study and canonical compare (`make reproduce`, `make reproduce-oos`, `make reproduce-insiders`); also `make test`, `make test-file F=...`, `make snapshot` | [research/AGENTS.md](backend/app/research/AGENTS.md) |
| `.github/workflows/ci.yml` | CI on every push/PR: backend pytest, frontend tsc + lint + build, both Docker images built (never pushed). Needs no secrets | |
| `.claude/workflows/feature-graph.js` | Multi-agent Plan/Build/Review/Verify/Critic workflow | [docs/AGENT_PROCESS.md](docs/AGENT_PROCESS.md) |
| `docker-compose.yml` | Dev: `db` (pgvector/pgvector:pg17) + `api` (built from `backend/`), both bound to 127.0.0.1 | |
| `docker-compose.prod.yml` | Production: `db` + `api` + `web` (frontend image). Needs an env file outside git with `POSTGRES_PASSWORD` and `ADMIN_TOKEN`; ports on 127.0.0.1 behind your TLS reverse proxy | its header comment |
| `.env.example` | Every optional env var with comments. Backend section: copy to `.env` (git-ignored), read by compose and the backend. Commented frontend section at the bottom: template for `frontend/.env.local` (Next never reads the root file) | |
| `.claude/launch.json` | Preview config: frontend dev server on :3000 | |

## Run everything

```bash
cp .env.example .env                 # optional; app runs on free sources without keys
docker compose up -d --build         # Postgres :5432 + API :8000, ingests on startup
npm --prefix frontend install        # first time only
npm --prefix frontend run dev        # UI on :3000 (API base: NEXT_PUBLIC_API_URL, default http://localhost:8000)
# frontend env (optional): copy the frontend section of .env.example into frontend/.env.local, uncommented
```

Python is not installed on the host. Run all Python through the `api` container:

```bash
docker compose build api                                       # code is COPYed into the image: rebuild after edits
docker compose run --rm api pytest -q                          # backend tests (agents: bash scripts/pytest.sh instead, no rebuild)
docker compose run --rm api python -m app.research.eventstudy  # event study (~15 min first run, cached after)
docker compose restart api                                     # API reloads event_study.json at startup
docker compose run --rm api python -m app.newsletter.build     # newsletter: last completed week (--week-end, --force, --preview)
docker compose run --rm api python -m app.research.oos          # pre-registered out-of-sample study -> event_study_oos.json
docker compose run --rm api python -m app.insiders.study       # Form 4 insider study -> event_study_insider_purchases.json (~1-2 h first run)
docker compose run --rm api python -m app.journal.digest verify # journal hash chain (seal | verify | export YYYY-MM-DD)
make reproduce                                                 # offline replay of the in-sample study vs docs/results (uses the api image)
```

## Env vars

Backend settings live in `backend/app/config.py` (table in [backend/AGENTS.md](backend/AGENTS.md)), documented in `.env.example`.
The frontend reads only `frontend/.env*` (table in [frontend/AGENTS.md](frontend/AGENTS.md)), documented in the commented frontend section of `.env.example` (template for `frontend/.env.local`).
The public site origin is configured twice and the values must match: `PUBLIC_BASE_URL` (root `.env`, newsletter links)
and `NEXT_PUBLIC_SITE_URL` (`frontend/.env.local`, canonical URLs, sitemap, robots; falls back to a `PUBLIC_BASE_URL` set there).

Added in the 2026-10-19 batch (all optional, all in `.env.example`):
- Admin protection (`AdminSettings` in `app/config.py`, policy in `app/security.py`): `ADMIN_TOKEN` (the old name `RESEARCH_ADMIN_TOKEN` is
  still accepted), `RESEARCH_JOBS_ENABLED`, `MUTATIONS_ENABLED`. Without a token or flag, mutations work only while `PUBLIC_BASE_URL` is localhost.
- Rate limits: `RATE_LIMIT_PER_MINUTE` (120), `RATE_LIMIT_WRITE_PER_MINUTE` (10), `TRUST_PROXY_HEADERS` (false).
- Email delivery (`DeliverySettings` in `app/delivery/settings.py`, not yet in `app.config.Settings`): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_TIMEOUT_SECONDS`, `EMAIL_FROM`, `EMAIL_REPLY_TO`, `EMAIL_POSTAL_ADDRESS`, `EMAIL_DAILY_DIGEST_HOUR_ET`,
  `EMAIL_MAX_PER_RUN`, `EMAIL_LINK_BASE_URL`, `EMAIL_TOKEN_SECRET`. Off unless `SMTP_HOST`, `EMAIL_FROM` and `EMAIL_POSTAL_ADDRESS` are all set.
- Not settings: `POSTGRES_PASSWORD` (prod compose env file), `GIT_SHA` (code version in study manifests), `REPRO_BUILD=1`
  (`scripts/reproduce.sh` rebuilds the api image first).

## Conventions (non-negotiable)

- **SEC User-Agent comes from config** (`settings.sec_user_agent`, env `SEC_USER_AGENT`). Pass it through;
  never hard-code a personal email or any contact string in code, tests or docs.
- **Research prices are Yahoo, personal use only** (`backend/app/research/prices.py`). Throttled, cached,
  never redistributed or served by the API. Anything public needs a licensed feed.
- **Agents never place orders.** No broker order code paths. Alpaca keys are paper keys used for news only.
- **No secrets in git.** Keys live in `.env` (ignored by `.gitignore`). Never commit live keys or `backend/data/`.
- Event-study design changes happen before looking at results, never after (see research/AGENTS.md). The OOS and
  insider studies are pre-registered (`backend/app/research/PREREGISTRATION_OOS.md`, `backend/app/insiders/PREREGISTRATION.md`);
  their CLIs never write `event_study.json` (the live evidence).
- **Every mutating endpoint goes through the admin policy** (`app/security.py`); never add an unprotected write
  except deliberate public ones (subscribe, newsletter preview), which the write-tier rate limit covers.
- **Email:** only double opt-in via `POST /api/subscribe`; never bulk-insert subscribers or send from tests (delivery/AGENTS.md).
- UI shows headlines and links out; never republish full article text.

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

**A page**
1. `frontend/src/app/<route>/page.tsx` (`"use client"` if it uses hooks). A page that must be crawlable (SEO) is a server
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
| Feed is missing or duplicating stories | `backend/app/pipeline/dedupe.py`, `ingest.py` (`is_duplicate`) |
| Wrong or missing tickers | `backend/app/pipeline/tickers.py`, `sources/edgar.py` (`tickers_for_cik`) |
| Wrong size bucket | `backend/app/pipeline/companies.py` (`BUCKETS`, `load_latest_floats`) |
| EDGAR parsing / 13D handling | `backend/app/sources/edgar.py` (`parse_entry`) |
| LLM summary, sentiment, flags, model choice | `backend/app/pipeline/enrich.py` |
| Live updates in the UI | `backend/app/pipeline/events.py`, `/api/stream` in `main.py`, `NewsFeed.tsx` |
| Event-study method or results | `backend/app/research/eventstudy.py`, `docs/results/`; other studies are served via `STUDY_FILES` in `main.py` (`/api/research/event-study?study=`) |
| Evidence line on signal cards | `load_study()` / `to_out()` in `main.py`, `ArticleCard.tsx` |
| Edge Lab charts | `frontend/src/app/lab/page.tsx`, `--div-*` tokens in `globals.css` |
| Strategy backtests | `backend/app/backtest/` (its own AGENTS.md) |
| Weekly newsletter content or schedule | `backend/app/newsletter/service.py`, `newsletter_cycle()` in `main.py`, `frontend/src/components/newsletter/` |
| SEO: ticker page text, metadata, sitemap, robots | `frontend/src/app/ticker/[symbol]/(view)/` (`summary.ts`), `app/sitemap.ts`, `app/robots.ts`, `/api/tickers/sitemap` in `main.py` |
| Admin token, 401/403 on writes, 429 rate limits | `backend/app/security.py`, `require_admin` in `main.py`, `send()` / `ApiError` in `frontend/src/lib/api.ts`, `/status` |
| Health, uptime, Status page | `backend/app/health.py`, `/api/health/*` in `main.py`, `frontend/src/app/status/` |
| Email list, newsletter emails, daily digest | `backend/app/delivery/` (its own AGENTS.md), `newsletter_cycle()` / `digest_cycle()` in `main.py`, `SubscribeForm.tsx` |
| Track-record seal (hash chain) | `backend/app/journal/digest.py`, `seal_cycle()` and `/api/journal/chain`, `/api/journal/verify` in `main.py`, `components/track/SealPanel.tsx` |
| Out-of-sample study, offline replay | `backend/app/research/oos.py`, `snapshot.py`, `scripts/reproduce.sh` |
| Insider-purchase (Form 4) study | `backend/app/insiders/` (its own AGENTS.md and PREREGISTRATION.md) |
| Learn lessons and simulators | `frontend/src/app/learn/`, `frontend/src/components/learn/`, `frontend/src/lib/learn/` |
| Production deploy, CI | `docker-compose.prod.yml`, `frontend/Dockerfile`, `.github/workflows/ci.yml` |
| Feasibility / product docs | `docs/` |
