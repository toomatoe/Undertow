# backend/app/delivery: email list, newsletter and daily digest delivery

Double-opt-in email list plus idempotent fan-out of the weekly "Small-Cap Filing Radar" (archived issue files from
`app/newsletter`) and a daily signal digest. **Off unless configured**: without `SMTP_HOST`, `EMAIL_FROM` and
`EMAIL_POSTAL_ADDRESS`, `POST /api/subscribe` returns 503, nothing is stored and the send functions return
`skipped_reason: "disabled"`. Tests never send: they use `FakeTransport`.

## Files

| File | Role |
|---|---|
| `settings.py` | `DeliverySettings` (pydantic BaseSettings, `.env`, `env_ignore_empty`), `get_delivery_settings()` (not cached). `enabled`, `link_base`, `site_base` properties |
| `transport.py` | `Transport` protocol (`send(EmailMessage)`), `SmtpTransport` (STARTTLS, or implicit TLS on 465, timeout, one reused connection until `close()`), `FakeTransport` (records; `fail_for` to simulate rejects) |
| `service.py` | `subscribe`, `confirm`, `unsubscribe`, `set_daily`, `status`, `purge_pending`, `send_newsletter`, `send_daily_digest`, `daily_digest_day`, `build_message` |
| `digest.py` | `build_daily_digest(session, data_dir, day_et)` -> dict with `markdown`, `html`, `flagged_words`; `subject`, `is_empty` |
| `routes.py` | `make_router(get_session, get_settings=None, make_transport=None)` and the default `router` |

## Env vars (all optional and off by default; listed in `.env.example`. Afterfile runs locally, so email stays off unless you add SMTP settings. `docker-compose.prod.yml` passes them through but is kept only for a possible later deployment)

These fields live in `DeliverySettings` only because this module was built in parallel with the config owner.
**They should move into `app.config.Settings` later** (same env names). `PUBLIC_BASE_URL` is read via `app.config.get_settings()`.

| Env var | Default | Notes |
|---|---|---|
| `SMTP_HOST` | none | required for `enabled` |
| `SMTP_PORT` | 587 | 465 = implicit TLS |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | none | password is a `SecretStr`; keep it in `.env` |
| `SMTP_STARTTLS` | true | ignored on port 465 |
| `SMTP_TIMEOUT_SECONDS` | 20 | |
| `EMAIL_FROM` | none | required, e.g. `Afterfile <radar@yourdomain>` on a domain with SPF/DKIM/DMARC |
| `EMAIL_REPLY_TO` | none | also the `mailto:` target in `List-Unsubscribe` |
| `EMAIL_POSTAL_ADDRESS` | none | required (CAN-SPAM physical address), printed in every footer |
| `EMAIL_DAILY_DIGEST_HOUR_ET` | 7 | 0..23. From this ET hour on day D, the digest for the finished day D-1 is due (default: before the 09:30 open) |
| `EMAIL_MAX_PER_RUN` | 500 | sends per fan-out call; the rest is `deferred` and goes out on the next call |
| `EMAIL_LINK_BASE_URL` | `PUBLIC_BASE_URL` | public origin where the API's `/api/...` routes are reachable (confirm/unsubscribe links). Set it to the API origin unless the site proxies `/api` to the backend |
| `EMAIL_TOKEN_SECRET` | auto | key for unsubscribe tokens. Unset: a random key is created once at `{DATA_DIR}/delivery/token_key` (volume, never in git). Changing/losing it invalidates every unsubscribe link already sent |

## Data kept (tables in `app/models.py`, created by `create_all`; no existing columns touched)

- `subscribers`: `email` (unique, lowercased, stripped), `status` pending|active|unsubscribed, `wants_daily`,
  `created_at`, `confirmed_at`, `unsubscribed_at` (UTC), `confirm_token_hash`, `manage_token_hash` (SHA-256 hex only),
  `source` (`"web"` for the API). **No IP addresses, user agents, opens or clicks.**
- `email_sends`: one row per (`subscriber_id`, `kind`, `ref`) (unique constraint). `kind` confirm|newsletter|daily_digest;
  `ref` = issue id (`2026-W42`) or ET date (`2026-10-19`; for confirm, the ET day it was sent). `status`: `sending`
  (transient claim made before the SMTP call), `sent`, `failed` (+ `error`, truncated to 300 chars).
- Tokens: the confirm token is random (`secrets.token_urlsafe(32)`), emailed once, valid 7 days
  (`CONFIRM_TTL_DAYS`, measured from the last sent confirm). The manage token (unsubscribe, daily toggle) is
  `base64url(HMAC-SHA256(key, "manage:" + email))`, so every message carries a working link while the DB stores only
  its SHA-256. Raw tokens appear only in emailed links.
- `purge_pending(session, days=30)` deletes never-confirmed rows older than 30 days. `purge_cycle()` in `main.py` runs it
  from the slow scheduler loop at most once per UTC day (even while delivery is off; test `test_purge_cycle_*` in `test_api.py`).

## Behaviour

- `subscribe`: always returns `{"message": GENERIC_MESSAGE}` (no enumeration). Active address: nothing changes, nothing
  is sent (an anonymous request can't change an active subscriber's preferences). New or unsubscribed: becomes pending.
  At most **one confirm email per address per ET day** (EmailSend key), which also limits abuse; a failed confirm send
  is retried on the next request. Rate limiting per client is the platform middleware's job (`/api/subscribe` write limit).
- `confirm`: pending -> active (`confirmed`); `already`, `expired`, or `invalid` (unknown token, or unsubscribed: an
  old confirm link never resubscribes).
- `unsubscribe`: immediate, idempotent; also clears `wants_daily` and the confirm token hash.
- Fan-out (`send_newsletter`, `send_daily_digest`): recipients ordered by id; rows `sent`/`sending` are skipped;
  `failed` rows are retried; each subscriber is re-read right before sending so an unsubscribe during a run is honoured.
  A row stuck in `sending` (crash mid-send) is never retried, to avoid a duplicate. Returns
  `{kind, ref, sent, failed, skipped, deferred}` or `{..., skipped_reason}` (`disabled`, `issue_not_found`,
  `flagged_words`, `empty`).
- `send_newsletter` reads `{id}.json|.html|.md` via `newsletter.load_issue/load_text`. It refuses an issue whose
  `flagged_words` (or a fresh `newsletter.flagged_words` for older issues) is non-empty. The plain part is the archived Markdown.
- `send_daily_digest` goes only to active subscribers with `wants_daily`. It skips days with no qualifying filings and
  no halts, and refuses when the digest's advice-word check flags anything.
- Digest timing: `daily_digest_day(now)` returns **yesterday's** ET date once today's ET hour >=
  `EMAIL_DAILY_DIGEST_HOUR_ET`, else `None`. Each digest covers one full finished ET day [00:00, 24:00) and
  `ref` = that date, so consecutive digests are contiguous: evening filings (EDGAR accepts until 22:00 ET, after-close
  8-Ks) land in the next morning's digest. Never pass today's date to `send_daily_digest`: that would claim the day's
  slot before the day is over and lose the rest of it (test `test_evening_filing_reaches_next_digest`).

## Daily digest content (`digest.py`)

Signal filings published on that ET calendar day with `severity >= 2` and a nano/micro/small `Company` (newsletter
`_filings`), severity 3 first, max 30: ticker, company, signal labels, size, form, filed time, EDGAR link, ticker-page
link (`PUBLIC_BASE_URL/ticker/SYM`) and the newsletter's `evidence_text` (20-day Edge Lab row, labelled "Historical,
hypothetical"), or "No historical Edge Lab statistic..." Plus the halts count (all halts, and serious small-cap ones).
No prices or float figures. It reuses `app.newsletter.service` helpers (`_filings`, `_filing_item`, `_evidence_index`,
`_study`, `_halts`, `evidence_text`, `banned_words` and the HTML style helpers); if those change, `tests/test_delivery.py` catches it.
`flagged_words` runs `newsletter.banned_words` over both renderings with tickers and company names blanked.

## Message rules (`build_message`, every message including the confirm email)

- `multipart/alternative`: plain-text part + HTML part.
- Headers: `List-Unsubscribe: <https://.../api/unsubscribe?token=...>` plus `, <mailto:REPLY_TO?subject=unsubscribe>`
  when `EMAIL_REPLY_TO` is set; `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058); `Message-ID`, `Date`,
  `Reply-To`. The message policy folds only past 998 chars: the stdlib default (78) RFC 2047-encodes the long URL and breaks the header.
- Footer (text and HTML): why you get it, the unsubscribe link, `Afterfile, EMAIL_POSTAL_ADDRESS`, and `DISCLAIMER`
  ("Research and education only, not financial advice. Historical statistics are not predictions.").

## Compliance checklist

- [x] Double opt-in: nothing but the one confirm email until the link is used; confirm links expire after 7 days.
- [x] Unsubscribe in every message (footer link + `List-Unsubscribe` one-click) and honoured immediately, even mid-run.
- [x] Physical postal address in every message (`EMAIL_POSTAL_ADDRESS` is required for `enabled`).
- [x] No purchased, scraped or imported lists: the only way onto the list is `POST /api/subscribe` + confirm. Never bulk-insert subscribers.
- [x] Accurate From/Subject; impersonal content only, advice-word check before every newsletter/digest send.
- [x] Privacy-minimal: no IPs, user agents or tracking pixels/click tracking; tokens stored hashed; unconfirmed sign-ups purged daily after 30 days.
- [ ] Operator: verified sending domain (SPF/DKIM/DMARC), a published privacy policy, and keep the unsubscribe working
      for at least 30 days after a send (don't rotate `EMAIL_TOKEN_SECRET` casually).

## API (`routes.py`, `APIRouter(prefix="/api")`)

| Route | Behaviour |
|---|---|
| `POST /api/subscribe` `{email, daily?}` | 202 `{message}` (generic); 503 `{detail: "Email delivery is not configured on this server"}` when disabled (nothing stored); 422 invalid email |
| `GET /api/subscribe/confirm?token=` | HTML page: 200 confirmed / already, 410 expired, 404 invalid |
| `GET /api/unsubscribe?token=` | HTML page with a POST button (GET never unsubscribes: mail scanners prefetch links) |
| `POST /api/unsubscribe?token=` | RFC 8058 one-click (body ignored), HTML 200; 404 unknown token |
| `POST /api/subscription/daily?token=&on=true\|false` | `{wants_daily}`; 404 unknown or unsubscribed |
| `GET /api/delivery/status` | `{enabled}` only |

Token pages send `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex` and a strict CSP.
`service.status(session)` (`{enabled, active, pending}`) is for admin/health use, not a public route.

## Wiring contract for `main.py` (owned by the platform item)

```python
from app.delivery import service as delivery
from app.delivery.routes import router as delivery_router
from app.delivery.settings import get_delivery_settings

app.include_router(delivery_router)            # uses app.db.get_session and SmtpTransport

def newsletter_cycle() -> None:                 # already runs in a thread
    with SessionLocal() as session:
        if built := newsletter.ensure_latest(session, settings.data_dir, **newsletter_kwargs()):
            log.info("Newsletter: built issue %s", built)
            if get_delivery_settings().enabled:
                try:
                    delivery.send_newsletter(session, settings.data_dir, built)
                except Exception:
                    log.exception("Newsletter email failed")

def digest_cycle() -> None:                     # call from the slow loop in a thread (asyncio.to_thread)
    if not get_delivery_settings().enabled:
        return
    day = delivery.daily_digest_day()           # YESTERDAY (ET) once today's hour >= EMAIL_DAILY_DIGEST_HOUR_ET, else None
    if day is None or state.last_digest_day == day:
        return
    with SessionLocal() as session:
        try:
            delivery.send_daily_digest(session, settings.data_dir, day)
            state.last_digest_day = day         # optional: sends are idempotent per (subscriber, day) anyway
        except Exception:
            log.exception("Daily digest email failed")
```

- Always use `daily_digest_day()` for the day; never `today_et()` (see "Digest timing"). If the scheduler is down for
  a whole day after the send hour, that day's digest is skipped (no backfill), never truncated.
- Skip both when not enabled (the functions also return `skipped_reason: "disabled"` on their own).
- Without a `transport` argument the send functions open one `SmtpTransport` and close it at the end. All calls block:
  run them in a thread, never on the event loop. Failures per recipient are rows, not exceptions; catch the rest.
- If a run hits `EMAIL_MAX_PER_RUN`, calling it again later sends the deferred remainder (idempotent). For the
  newsletter, `ensure_latest` returns the id only once, so re-call `send_newsletter` with the latest issue id
  (e.g. `newsletter.list_issues(...)[0]["id"]`) on later cycles if the list ever exceeds the cap.
- `purge_cycle()` calls `delivery.purge_pending(session)` once per UTC day (in a thread, failures logged and retried next cycle).

Tests: `bash scripts/pytest.sh tests/test_delivery.py` (in-memory SQLite, `FakeTransport`, a minimal FastAPI app with only this router).
Repo graph: module `delivery` in `docs/agent-graph.json` (shared resource: the SMTP provider).
