# backend/: FastAPI app

Python 3.12, FastAPI, SQLAlchemy 2.0, pydantic-settings, httpx, feedparser, anthropic SDK.
Pinned versions in `requirements.txt`; `requirements-dev.txt` adds pytest.

## Layout

| File | Role |
|---|---|
| `app/main.py` | FastAPI app, `lifespan`, background `scheduler()`, every `/api/*` route, `AppState` (`state`) |
| `app/config.py` | `Settings` + cached `get_settings()` |
| `app/db.py` | `engine`, `SessionLocal`, `Base`, `init_db()`, `_add_missing_columns()`, `get_session()` dependency |
| `app/models.py` | ORM tables |
| `app/schemas.py` | Pydantic response models (mirrored by `frontend/src/lib/api.ts`) |
| `app/sources/` | Source adapters ([AGENTS.md](app/sources/AGENTS.md)) |
| `app/pipeline/` | Ingest cycle ([AGENTS.md](app/pipeline/AGENTS.md)) |
| `app/research/` | Event study + prices ([AGENTS.md](app/research/AGENTS.md)) |
| `app/backtest/` | Portfolio backtester, run log, readiness gates, borrow archiver ([AGENTS.md](app/backtest/AGENTS.md)) |
| `app/journal/` | Forward signal journal ([AGENTS.md](app/journal/AGENTS.md)) |
| `app/alerts/` | Discord alerts, halt storage, alert log ([AGENTS.md](app/alerts/AGENTS.md)) |
| `app/fundamentals/` | Cash runway, dilution, short interest ([AGENTS.md](app/fundamentals/AGENTS.md)) |
| `app/newsletter/` | Weekly newsletter: `service.py` (build, render, archive), `build.py` (CLI) ([AGENTS.md](app/newsletter/AGENTS.md)) |
| `tests/` | pytest; `pytest.ini` sets `pythonpath = .`, `testpaths = tests` |

## Startup (`lifespan` in main.py)

`init_db()` -> `broadcaster.bind_loop()` -> `TickerUniverse.load(data_dir, sec_user_agent)` ->
`load_companies()` (public-float frames -> `sync_companies` -> `state.sizes`) -> `backfill_signals()` ->
`load_study()` (reads `{data_dir}/event_study.json`, keeps 20-day rows as `state.evidence`) ->
`Enricher` if `ANTHROPIC_API_KEY` set -> `Alerter` hook -> `scheduler()` task (every `INGEST_INTERVAL_SECONDS`, each step
in a thread with its own try/except: `run_ingest`, IBKR borrow snapshot, `journal_cycle()`, `newsletter_cycle()`) and,
when `EDGAR_POLL_SECONDS` > 0, `edgar_poller()` (fast EDGAR poll + Nasdaq halts). `newsletter_cycle()` calls
`newsletter.ensure_latest`, which builds the most recently completed week (ending Sunday, ET) once and is a no-op
afterwards; issues are files under `{data_dir}/newsletters/`, not DB rows. `to_out()` attaches `size_bucket` to tickers and `Evidence` per (signal, bucket).

## Config / env (`app/config.py`)

pydantic-settings, case-insensitive env names, also reads `.env` from the cwd. All optional.

| Env var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/quantdesk.db` | compose sets Postgres (`postgresql+psycopg://...@db:5432/quantdesk`) |
| `DATA_DIR` | `./data` | compose: `/app/data` (volume `apidata`). SEC caches, prices, `event_study.json` |
| `SEC_USER_AGENT` | `quantdesk-dev contact@example.com` | used for every SEC request and RSS. Never hard-code one |
| `RSS_FEEDS` | `DEFAULT_RSS_FEEDS` | JSON object name -> url |
| `EDGAR_ENABLED` | `true` | |
| `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` | none | both set -> `alpaca_enabled`. Paper keys only |
| `ANTHROPIC_API_KEY` | none | set -> `enrich_enabled` |
| `ENRICH_MODEL` | `claude-opus-5-5` | |
| `ENRICH_MAX_PER_CYCLE` / `FILING_TEXT_MAX_PER_CYCLE` | 25 / 40 | per-cycle caps |
| `INGEST_INTERVAL_SECONDS` / `INGEST_ON_STARTUP` | 300 / true | |
| `EDGAR_POLL_SECONDS` | 30 | fast EDGAR + halts loop; 0 disables it (EDGAR joins the slow cycle) |
| `DISCORD_WEBHOOK_URL` | none | set -> alerts go to Discord. Keep it in `.env` |
| `ALERT_MIN_SEVERITY` / `ALERT_SIZES` / `ALERT_MAX_AGE_MINUTES` | 2 / `["nano","micro","small"]` / 15 | alert filters (see alerts/AGENTS.md) |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list |
| `PUBLIC_BASE_URL` | `http://localhost:3000` | public site origin for newsletter links (ticker pages, methodology, track record, Edge Lab, disclaimer, archive). The frontend reads its own `NEXT_PUBLIC_SITE_URL` (frontend/AGENTS.md); keep them equal |

`get_settings()` is `lru_cache`d and `db.engine` is built at import time, so env must be set before
`app.*` is imported (that is why `tests/conftest.py` sets env at module top).

## Database and models (`app/models.py`)

- `Article`: one row per news item or filing. `url_hash` (unique) / `title_hash` for dedupe; `source`
  (`rss|edgar|alpaca`); filing fields `form`, `cik`, `signals` (JSON list of codes, most severe first),
  `severity` (max), `body` (filing text, `""` = tried and failed); enrichment fields `ai_summary`,
  `sentiment` (-1..1), `sentiment_label`, `event_type`, `relevance`, `ai_flags`, `enrich_model`, `enriched_at`.
- `ArticleTicker`: (article_id, symbol) PK, `method` in `vendor|cashtag|exchange|edgar|llm`. Loaded `selectin`.
- `Company`: symbol -> cik, name, `public_float`, `float_as_of`, `size_bucket`. Fully replaced at startup.
- `WatchlistItem`, `IngestRun` (per-source fetched/inserted/error, shown by `/api/status`).
- Timestamps are UTC. SQLite drops tzinfo; `ArticleOut.assume_utc` re-adds it.
- Signal filtering uses `cast(Article.signals, String).like('%"code"%')` to work on both SQLite and Postgres.

## Stopgap migration (`db._add_missing_columns`)

No Alembic yet. `init_db()` runs `create_all()` then, for each model column missing from an existing
table, issues `ALTER TABLE ... ADD COLUMN` and creates its single-column index. It raises `RuntimeError`
for a non-nullable column. So: **new columns must be nullable**; renames, type changes and drops are not
migrated (do them by hand or introduce Alembic). Test against an existing Postgres volume, not just a fresh DB.

## Testing patterns

Research launches: `GET /api/research/jobs` returns the active job and latest job per kind;
`POST /api/research/jobs/{kind}` starts `backtest` or `event_study` (202; 409 while busy).
`app/research_jobs.py` manages fixed subprocess workloads and persisted job status under `DATA_DIR`.
The local development API uses one worker. Launch gate (`research_launch_policy` in `app/main.py`):
- If `RESEARCH_ADMIN_TOKEN` is set, POST requires `Authorization: Bearer <token>`. Otherwise it gets 401; the token is compared in constant time.
- Else, if `RESEARCH_JOBS_ENABLED=true|false` is set, it decides.
- Else, launches are allowed only when `PUBLIC_BASE_URL` is a localhost origin; otherwise they get 403.

GET also returns `enabled` and `requires_token`, never the token. A corrupt `research_jobs.json` is moved to
`.corrupt-<timestamp>` and the API starts with empty status. Compose binds the API and Postgres to 127.0.0.1, so the localhost
default isn't reachable from the LAN. Study completion refreshes in-memory evidence without an API restart.
Tests in `tests/test_research_jobs.py` use offline substitute workers.

Run: `bash scripts/pytest.sh [tests/test_x.py ...]` from the repo root. It mounts `backend/` into the
`quantdesk-api-test` dependency image, so it tests the current source without a rebuild and is safe to run in
parallel. Rebuild that image only when requirements change (`docker build -q -t quantdesk-api-test backend`).
The full path (`docker compose build api && docker compose run --rm api pytest -q`) bakes code into the image;
in multi-agent runs only the Verify step uses it (docs/AGENT_PROCESS.md).

- `tests/test_newsletter.py` covers the newsletter build, renderers, archive and the banned-word check;
  `tests/test_api.py` covers `/api/tickers/sitemap` (routed before `/api/tickers/{symbol}`, Company filter, `days`).

- `tests/conftest.py` sets `DATABASE_URL=sqlite:///:memory:` and removes `ANTHROPIC_API_KEY` before imports.
  `_make_engine` uses `StaticPool` for `:memory:` so every session shares one DB.
- Modules reset schema in `setup_module()` with `Base.metadata.drop_all/create_all(engine)`.
- API tests use `client = TestClient(app)` **without** `with`, so `lifespan` (network SEC downloads,
  scheduler) never runs. Seed DB rows directly and set `state.sizes` / `state.evidence` by hand.
- Enrichment tests build `Enricher(api_key="test-key", ...)` then replace `e.client` with a
  `SimpleNamespace` exposing `messages.create` and `beta.messages.create` that record kwargs and return a
  fake response (`stop_reason`, `content=[SimpleNamespace(type="text", text=...)]`).
- Source/research tests feed canned payloads to pure functions (`parse_entry`, `parse_items`,
  `parse_frame`, `parse_chart`, `summarize`, `day0_index`, `measure`); use `monkeypatch` for constants
  like `eventstudy.HORIZONS`. Tests must never hit the network or the LLM.

## Docker

- `Dockerfile`: `python:3.12-slim`, installs `requirements-dev.txt`, copies the code, runs
  `uvicorn app.main:app --host 0.0.0.0 --port 8000`. `.dockerignore` excludes `data/` and `.env`.
- Compose `api` gets `.env` via `env_file` (optional) and overrides `DATABASE_URL` and `DATA_DIR`.
- No-Docker fallback (needs host Python): `pip install -r requirements.txt && uvicorn app.main:app --reload`
  from `backend/`, using SQLite under `backend/data/` (git-ignored).
