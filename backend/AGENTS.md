# backend/: FastAPI app

Python 3.12, FastAPI, SQLAlchemy 2.0, pydantic-settings, httpx, feedparser, anthropic SDK.
The API runs locally (compose binds it to 127.0.0.1:8000; the site is http://localhost:3000). Every default works
with zero configuration and every optional integration is off until its env vars are set.
Pinned versions in `requirements.txt`; `requirements-dev.txt` adds pytest.

## Layout

| File | Role |
|---|---|
| `app/main.py` | FastAPI app, `lifespan`, background `scheduler()`, every `/api/*` route except the delivery router it mounts, `AppState` (`state`), `STUDY_FILES` allowlist, middleware wiring |
| `app/config.py` | `AdminSettings` (admin token / flags) and `Settings(AdminSettings)` + cached `get_settings()` |
| `app/security.py` | Admin policy for every mutating endpoint (`admin_policy`, `admin_dependency`) and the per-client rate limiter (`RateLimiter`, `RateLimitMiddleware`) |
| `app/health.py` | Pure health evaluation (`evaluate(HealthInputs)`), uptime snapshots (`append_snapshot`, `read_snapshots`, `history`) in `{data_dir}/uptime.jsonl` |
| `app/research_jobs.py` | Background research subprocesses (`MODULES`: `backtest`, `event_study`, `event_study_oos`, `insider_study`), persisted job status |
| `app/db.py` | `engine`, `SessionLocal`, `Base`, `init_db()`, `_add_missing_columns()`, `get_session()` dependency |
| `app/models.py` | ORM tables |
| `app/schemas.py` | Pydantic response models (mirrored by `frontend/src/lib/api.ts`) |
| `app/sources/` | Source adapters ([AGENTS.md](app/sources/AGENTS.md)) |
| `app/pipeline/` | Ingest cycle ([AGENTS.md](app/pipeline/AGENTS.md)) |
| `app/research/` | Event study (`StudyDesign`), out-of-sample study (`oos.py`), replay manifests (`snapshot.py`), prices, working-paper number check (`paper_numbers.py`) ([AGENTS.md](app/research/AGENTS.md)) |
| `app/insiders/` | Separate pre-registered Form 4 insider-purchase study, plus the live insider-cluster forward test (`live.py` poller, `settings.py` `InsiderLiveSettings`, `evidence.py` forward-test evidence row) ([AGENTS.md](app/insiders/AGENTS.md)) |
| `app/paper/` | Hypothetical paper portfolio simulated from the journal (`service.build_portfolio`), served by `GET /api/paper-portfolio`. No execution code ([AGENTS.md](app/paper/AGENTS.md)) |
| `app/delivery/` | Email list, newsletter/digest delivery, `/api/subscribe` router, own `DeliverySettings` ([AGENTS.md](app/delivery/AGENTS.md)) |
| `app/backtest/` | Portfolio backtester, run log, readiness gates, borrow archiver ([AGENTS.md](app/backtest/AGENTS.md)) |
| `app/journal/` | Forward signal journal (per-signal `EVALUATION_HORIZONS`) + tamper-evident hash chain `digest.py` ([AGENTS.md](app/journal/AGENTS.md)) |
| `app/alerts/` | Discord alerts, halt storage, alert log ([AGENTS.md](app/alerts/AGENTS.md)) |
| `app/fundamentals/` | Cash runway, dilution, short interest ([AGENTS.md](app/fundamentals/AGENTS.md)) |
| `app/newsletter/` | Weekly newsletter: `service.py` (build, render, archive), `build.py` (CLI) ([AGENTS.md](app/newsletter/AGENTS.md)) |
| `tests/` | pytest; `pytest.ini` sets `pythonpath = .`, `testpaths = tests`; `tests/fixtures/form4/` = insider-study fixtures, `tests/fixtures/form4_live/` = live forward-test fixtures |

## Startup (`lifespan` in main.py)

`get_research_jobs()` -> `init_db()` -> `broadcaster.bind_loop()` -> `TickerUniverse.load(data_dir, sec_user_agent)` ->
`load_companies()` (public-float frames -> `sync_companies` -> `state.sizes`) -> `backfill_signals()` ->
`load_study()` (reads `{data_dir}/event_study.json`, keeps 20-day rows as `state.evidence`) ->
`load_forward_evidence()` (the insider study's micro / 5-day `insider_cluster_purchase` row via `insiders/evidence.py` ->
`state.forward_evidence`; never from `event_study.json`) ->
`Enricher` if `ANTHROPIC_API_KEY` set -> `Alerter` hook -> `scheduler()` task (every `INGEST_INTERVAL_SECONDS`, each step
in a thread with its own try/except: `run_ingest`, IBKR borrow snapshot, `journal_cycle()`, `seal_cycle()`,
`newsletter_cycle()`, `digest_cycle()`, then the `last_slow_cycle` heartbeat and `uptime_cycle()`) and,
when `EDGAR_POLL_SECONDS` > 0, `edgar_poller()` (fast EDGAR poll + Nasdaq halts; heartbeats `last_edgar_poll`,
`last_halts_poll`). The fast poll (`pipeline.ingest.poll_edgar`) also runs the **live Form 4 insider-cluster forward
test** (`_poll_form4` -> `app.insiders.live.poll_form4`, own try/except, gated on `EDGAR_ENABLED` and
`INSIDER_LIVE_ENABLED`); with `EDGAR_POLL_SECONDS=0` it runs in `run_ingest` instead. `newsletter_cycle()` calls `newsletter.ensure_latest`, which builds the most recently completed
week (ending Sunday, ET) once and is a no-op afterwards; issues are files under `{data_dir}/newsletters/`, not DB rows.
A newly built issue is emailed with `delivery.send_newsletter` when delivery is enabled. `seal_cycle()` seals the
journal hash chain through yesterday (UTC) once per day and drops the verify cache. `digest_cycle()` sends the daily
email digest for yesterday (ET) once per ET day after `EMAIL_DAILY_DIGEST_HOUR_ET` (only when delivery is enabled).
`uptime_cycle()` appends one health snapshot to `{data_dir}/uptime.jsonl`. `to_out()` attaches `size_bucket` to tickers and `EvidenceOut` per (signal, bucket):
main-study evidence for `ALL_SIGNALS` codes, forward-test evidence (`study="insider_purchases"`, `forward_test=true`) for
`FORWARD_TEST_SIGNALS` codes, and sets `ArticleOut.forward_test`.

## Optional schema fields and the paper-portfolio endpoint (v1.0)

All additive and optional, so older clients keep working:
- `SignalOut.forward_test` (default false; true for `FORWARD_TEST_SIGNALS`), `ArticleOut.forward_test`.
- `EvidenceOut(Evidence)` adds `study`, `forward_test`, `t_stat_clustered`, `companies` (all defaulted). It is a
  subclass so study rows can still be loaded with `Evidence.model_fields` as the key list.
- `/api/journal` entries and `/api/journal/summary` rows carry `evaluation_horizon` and `forward_test_label` (null
  unless a forward test). `/api/signals/catalog` lists main signals, then forward-test signals.
- `GET /api/paper-portfolio?hedge=false&max_concurrent=20` (`max_concurrent` 1..100) -> `PaperPortfolioOut`
  (`PaperAssumptions`, `PaperEquityPoint`, `PaperTotals`, `PaperSignalRow`, `PaperPosition`): hypothetical portfolio
  from `app.paper.service.build_portfolio` with the notional fixed server-side (`PAPER_NOTIONAL` = 10,000). Public,
  read-only, rate-limited by the middleware, cache-only prices (no network), cached in `state.paper_cache` per (ET
  date, hedge, max_concurrent) for `PAPER_TTL_SECONDS` (600) under `paper_lock`. Rules in app/paper/AGENTS.md.

Middleware: `RateLimitMiddleware` (limiter looked up per request via the module-level `rate_limiter`, so tests can
swap it), then `CORSMiddleware` added last (outermost, so 429s carry CORS headers). `app.include_router(delivery_router)`
mounts `/api/subscribe`, `/api/subscribe/confirm`, `/api/unsubscribe` (GET page + POST one-click),
`/api/subscription/daily`, `/api/delivery/status` (see delivery/AGENTS.md).

## Platform: admin policy, rate limits, health (`app/security.py`, `app/health.py`)

- **Admin policy** (`current_admin_policy(scope)` in main.py -> `security.admin_policy`): a configured `ADMIN_TOKEN`
  (or `RESEARCH_ADMIN_TOKEN`) always wins and requires `Authorization: Bearer <token>` (constant-time compare; missing
  or wrong -> 401 with `WWW-Authenticate: Bearer`). Without a token the scope's flag decides (`research`:
  `RESEARCH_JOBS_ENABLED`, falling back to `MUTATIONS_ENABLED`; `mutations`: `MUTATIONS_ENABLED`); off -> 403. Without
  either, allowed only when `PUBLIC_BASE_URL` is a local origin (localhost, 127.0.0.1, ::1, `*.localhost`).
  Protected routes: `POST /api/research/jobs/{kind}` (scope `research`), `POST /api/ingest`, `POST /api/alerts/test`,
  `PUT`/`DELETE /api/watchlist/{symbol}` (scope `mutations`). `GET /api/status` returns `admin: {protected,
  mutations_enabled}`; `GET /api/research/jobs` returns `enabled`, `requires_token`. The token is never returned.
- **Rate limits** (`RateLimiter`): in-memory sliding 60 s window per client key, two tiers: every request
  (`RATE_LIMIT_PER_MINUTE`) and writes POST/PUT/PATCH/DELETE (`RATE_LIMIT_WRITE_PER_MINUTE`); 0 disables a tier.
  Over the limit -> 429 with `Retry-After`. Exempt: `/api/stream`, `/api/health`, CORS preflights and Starlette's
  `testclient` peer (so `TestClient` tests are never limited unless they build their own limiter). The key is the peer
  IP, or with `TRUST_PROXY_HEADERS=true` and a private/loopback peer, the right-most `X-Forwarded-For` hop outside
  those ranges. Per process: the API runs one worker.
- **Health**: `GET /api/health` is a cheap liveness check (no DB; container healthcheck). `GET /api/health/details`
  = `health.evaluate(health_inputs())`: components `db`, `ingest`, `edgar_poller`, `halts_poller`, `journal`,
  `newsletter`, `alerts`, `email`, `research_job`; overall `down` when the DB check fails, `degraded` when `ingest`
  (last successful run older than 3 x `INGEST_INTERVAL_SECONDS`) or `edgar_poller` (older than 300 s on a weekday
  06:00-22:00 ET) is degraded, else `ok`; thresholds are echoed under `thresholds`. `GET /api/health/history?days=7`
  (1..30) = uptime % per component and per day plus status transitions from `uptime.jsonl` (lines older than 30 days dropped).

## Files under `DATA_DIR` added in this batch

`journal_chain.jsonl` (hash chain, append-only), `uptime.jsonl`, `delivery/token_key` (when `EMAIL_TOKEN_SECRET` is
unset), `event_study_oos.json`, `event_study_insider_purchases.json`, `insider_datasets/`, `insider_xml/`,
`submissions/pages/`, `snapshots/` (hash-only manifests and replay outputs); v1.0 adds `insider_live_seen.json` (Form 4
accession seen-set) and `insider_live_purchases.jsonl` (qualifying live purchases). All live in the `apidata` volume, never in git.

## Config / env (`app/config.py`)

pydantic-settings, case-insensitive env names, also reads `.env` from the cwd. All optional. `env_ignore_empty=True`:
a blank `NAME=` line counts as unset.

| Env var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/undertow.db` | compose sets Postgres (`postgresql+psycopg://...@db:5432/quantdesk`; the local Postgres user/db keep the project's original name so existing volumes still work) |
| `DATA_DIR` | `./data` | compose: `/app/data` (volume `apidata`). SEC caches, prices, `event_study.json` |
| `SEC_USER_AGENT` | `undertow-dev contact@example.com` | used for every SEC request and RSS. Never hard-code one |
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
| `PUBLIC_BASE_URL` | `http://localhost:3000` | **site** origin (the frontend, not the API at :8000) for newsletter and email links (ticker pages, methodology, track record, Edge Lab, disclaimer, archive); a localhost value also opens mutations by default (admin policy). The frontend reads its own `NEXT_PUBLIC_SITE_URL` (frontend/AGENTS.md); keep them equal |
| `ADMIN_TOKEN` (alias `RESEARCH_ADMIN_TOKEN`) | none | `SecretStr` in `AdminSettings`. Set: every protected endpoint needs `Authorization: Bearer <token>`. `ADMIN_TOKEN` wins when both are set |
| `RESEARCH_JOBS_ENABLED` | none | without a token: research launches on/off (falls back to `MUTATIONS_ENABLED`) |
| `MUTATIONS_ENABLED` | none | without a token: ingest, alerts/test, watchlist changes on/off. Unset (and no token): on only for a localhost `PUBLIC_BASE_URL` |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_WRITE_PER_MINUTE` | 120 / 10 | per client, sliding 60 s; 0 disables that tier |
| `TRUST_PROXY_HEADERS` | false | use `X-Forwarded-For` (right-most hop outside private/loopback ranges) when the peer is a private/loopback proxy |
| `INSIDER_LIVE_ENABLED` | `true` | live insider-cluster forward test in the fast EDGAR poller (also needs `EDGAR_ENABLED`); read by `app/insiders/settings.py` `InsiderLiveSettings` (not `Settings`, yet). `false` stops all Form 4 requests |
| `SMTP_*`, `EMAIL_*` | none | optional, off by default: email delivery; read by `app/delivery/settings.py` `DeliverySettings` (not `Settings`, yet). Full table in [delivery/AGENTS.md](app/delivery/AGENTS.md) |

Not settings: `GIT_SHA` (read by `app.research.snapshot` for manifests; `unknown` when unset), `UNDERTOW_REPO_ROOT`
(repo root for `app.research.paper_numbers.find_repo_root`; else `/repo` when it has `docs/`, else the checkout).

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
- `Subscriber` (`subscribers`: email unique, `status` pending|active|unsubscribed, `wants_daily`, hashed tokens, no IPs)
  and `EmailSend` (`email_sends`: unique (`subscriber_id`, `kind`, `ref`), makes sends idempotent). New tables, created by
  `create_all`; details in delivery/AGENTS.md.
- Timestamps are UTC. SQLite drops tzinfo; `ArticleOut.assume_utc` re-adds it.
- Signal filtering uses `cast(Article.signals, String).like('%"code"%')` to work on both SQLite and Postgres.

## Stopgap migration (`db._add_missing_columns`)

No Alembic yet. `init_db()` runs `create_all()` then, for each model column missing from an existing
table, issues `ALTER TABLE ... ADD COLUMN` and creates its single-column index. It raises `RuntimeError`
for a non-nullable column. So: **new columns must be nullable**; renames, type changes and drops are not
migrated (do them by hand or introduce Alembic). Test against an existing Postgres volume, not just a fresh DB.

## Testing patterns

Research launches: `GET /api/research/jobs` returns the active job and latest job per kind;
`POST /api/research/jobs/{kind}` starts `backtest`, `event_study`, `event_study_oos` or `insider_study`
(202; 409 while busy; 422 unknown kind). `app/research_jobs.py` manages fixed subprocess workloads and persisted job
status under `DATA_DIR`. The local development API uses one worker. Launch gate: the admin policy with scope `research`
(`research_launch_policy` in `app/main.py`, rules above under "Platform"):
- If `ADMIN_TOKEN` (or `RESEARCH_ADMIN_TOKEN`) is set, POST requires `Authorization: Bearer <token>`. Otherwise it gets 401; the token is compared in constant time.
- Else, if `RESEARCH_JOBS_ENABLED=true|false` (or, failing that, `MUTATIONS_ENABLED`) is set, it decides.
- Else, launches are allowed only when `PUBLIC_BASE_URL` is a localhost origin; otherwise they get 403.

GET also returns `enabled` and `requires_token`, never the token. A corrupt `research_jobs.json` is moved to
`.corrupt-<timestamp>` and the API starts with empty status. Compose binds the API and Postgres to 127.0.0.1, so the localhost
default isn't reachable from the LAN. Only a successful `event_study` run refreshes in-memory evidence (no API restart);
the OOS and insider studies write their own files, served by `GET /api/research/event-study?study=oos|insider_purchases`
(`STUDY_FILES` allowlist; `GET /api/research/studies` lists availability, `generated_at`, `n_tests`, `design`).
Tests in `tests/test_research_jobs.py` use offline substitute workers.

Run: `bash scripts/pytest.sh [tests/test_x.py ...]` from the repo root. It mounts `backend/` at `/app` and the repo
root read-only at `/repo` into the `undertow-api-test` dependency image, so it tests the current source without a
rebuild and is safe to run in parallel. The `/repo` mount lets tests compare backend code with `docs/` and `frontend/`
(`test_paper_numbers.py`, `test_insider_live.py::test_bundled_row_matches_docs_results`); without it those checks skip. Rebuild that image only when requirements change (`docker build -q -t undertow-api-test backend`).
The full path (`docker compose build api && docker compose run --rm api pytest -q`) bakes code into the image;
in multi-agent runs only the Verify step uses it (docs/AGENT_PROCESS.md).

- `tests/test_newsletter.py` covers the newsletter build, renderers, archive and the banned-word check;
  `tests/test_api.py` covers `/api/tickers/sitemap` (routed before `/api/tickers/{symbol}`, Company filter, `days`),
  the study allowlist (`/api/research/studies`, `?study=`), research kinds, the journal chain endpoints, `seal_cycle`,
  the mounted delivery router and the gated newsletter/digest email hooks.
- Batch 2026-10-19 test files: `test_security.py` (admin policy on the real routes, token alias, blank env values,
  rate limiter tiers/exemptions, proxy keys, subscribe/preview on the write tier), `test_health.py`
  (component thresholds, uptime history), `test_delivery.py` (minimal app with only the delivery router, `FakeTransport`),
  `test_journal_digest.py` (hash chain), `test_oos.py`, `test_snapshot.py`, `test_insiders.py` (fixtures in
  `tests/fixtures/form4/`). None touch the network or send email.
- v1.0 (local-only) test files: `test_paper_portfolio.py` (P&L, costs, horizons, capacity, hedge, cache-file choice,
  endpoint with the network patched to fail, no-execution-code grep), `test_insider_live.py` (live Form 4 poller, fixtures
  in `tests/fixtures/form4_live/`), `test_paper_numbers.py` (paper vs `docs/results`, frontend copy identical; needs
  `/repo`), `test_config_local.py` (zero-config local defaults: localhost site origin, integrations off, open local
  admin). `test_api.py` adds the forward-test signal/evidence path; `test_journal.py` the evaluation horizons.

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
- Compose `api` gets `.env` via `env_file` (optional) and overrides `DATABASE_URL` and `DATA_DIR`. The `web` service
  (frontend image) sits behind the `web` profile: `docker compose --profile web up -d --build` (or `scripts/start.ps1`).
- `docker-compose.prod.yml` (repo root) is **optional, for later**, not used by the local-only setup (never deploy
  publicly with Yahoo prices): `db` (password from `POSTGRES_PASSWORD`, never published), `api` (requires
  `ADMIN_TOKEN`; healthcheck polls `/api/health`; ports on 127.0.0.1) and `web` (frontend image). It passes only an
  explicit list of env vars to the api (see its `environment:` block); other settings, e.g. `SMTP_STARTTLS`,
  `EMAIL_DAILY_DIGEST_HOUR_ET`, `MUTATIONS_ENABLED`, keep their defaults there unless added to that block.
- CI (`.github/workflows/ci.yml`) runs `pip install -r requirements-dev.txt && pytest -q` on Python 3.12 directly.
- No-Docker fallback (needs host Python): `pip install -r requirements.txt && uvicorn app.main:app --reload`
  from `backend/`, using SQLite under `backend/data/` (git-ignored).
