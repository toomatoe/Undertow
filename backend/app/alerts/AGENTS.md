# backend/app/alerts: real-time signal alerts

Pushes new filing signals to Discord within seconds of detection, and logs every decision
with its detection latency. That latency is the product's speed metric; competitors claim
under 60 s.

## Pipeline

1. `main.edgar_poller` calls `pipeline.ingest.poll_edgar` every `EDGAR_POLL_SECONDS` (default 30). It fetches only the EDGAR feeds, with no filing text and no enrichment, so it stays fast.
   - With polling on, the slow 5-minute cycle leaves EDGAR out (`build_sources(include_edgar=False)`), so the two never double-fetch.
2. Each newly stored article id goes to every hook in `pipeline.ingest.NEW_ARTICLE_HOOKS`, after commit, in the ingest thread. `Alerter` is registered in `main.lifespan`.
3. `Alerter.handle` → `decide()` → `format_message()` → POST to the Discord webhook → write an `AlertLog` row (`sent` / `skipped` + reason / `failed` + exception name).

## Rules (`decide`, all configurable in `.env`)

- EDGAR article with signals: news never alerts and isn't logged.
- `severity >= ALERT_MIN_SEVERITY` (default 2).
- Filed within `ALERT_MAX_AGE_MINUTES` (default 15), so a restart never replays backlog.
- Ticker on the watchlist (always alerts), **or** company size in `ALERT_SIZES` (default nano, micro, small).
- No `DISCORD_WEBHOOK_URL` means the decision is logged as `skipped: no_channel_configured`.

## Message content rules

Alerts are impersonal publications (see the legal section of `docs/PRODUCT_RESEARCH.md`):

- State what was filed, size and float, and the Edge Lab historical stat with n and significance.
- **Never** buy/sell language, price targets or personalization. `tests/test_alerts.py` checks this.
- Footer disclaimer: historical stats are hypothetical, not advice.

## Adding a channel (email, Web Push, Telegram)

Add a sender beside the Discord POST in `Alerter.handle`, keyed by config. Keep one `AlertLog` row per channel.
Delivery errors must be caught and logged: an exception in a hook is swallowed by ingest but would lose the log row.

## API

- `GET /api/alerts?limit=`: config, `latency_median_s` / `latency_p90_s`, counts by status/reason, recent log.
- `POST /api/alerts/test`: sends a test message to the configured webhook.

Tests: `backend/tests/test_alerts.py`, with a fake `post`, a fixed `now` and an in-memory DB.
