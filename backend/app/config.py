from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RSS_FEEDS = {
    "CNBC Top News": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "CNBC Markets": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "MarketWatch Top Stories": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "MarketWatch MarketPulse": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
    "Seeking Alpha Market Currents": "https://seekingalpha.com/market_currents.xml",
    "Investing.com News": "https://www.investing.com/rss/news.rss",
    "PR Newswire": "https://www.prnewswire.com/rss/news-releases-list.rss",
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
}


class AdminSettings(BaseSettings):
    """Who may change server state (policy in app/security.py). Settings inherits these fields.

    env_ignore_empty: a blank `ADMIN_TOKEN=` or `MUTATIONS_ENABLED=` line in .env means "unset", not a startup error.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # When set, every mutating endpoint requires "Authorization: Bearer <token>". RESEARCH_ADMIN_TOKEN (the older,
    # research-only name) is still accepted as a fallback; ADMIN_TOKEN wins when both are set.
    admin_token: SecretStr | None = Field(None, validation_alias=AliasChoices("admin_token", "research_admin_token"))
    # Without a token: explicit on/off for research launches (falls back to MUTATIONS_ENABLED) ...
    research_jobs_enabled: bool | None = None
    # ... and for the other mutations (ingest, alerts/test, watchlist). Unset: on only for a local PUBLIC_BASE_URL.
    mutations_enabled: bool | None = None

    @property
    def research_admin_token(self) -> SecretStr | None:
        """Backwards-compatible name for admin_token."""
        return self.admin_token


class Settings(AdminSettings):
    """Backend settings. Undertow runs locally on your own machine; every default works with zero configuration.

    Site origin (frontend) http://localhost:3000, API origin http://localhost:8000. Every optional integration is off
    while its env vars are unset: Alpaca news (both keys), Claude enrichment (ANTHROPIC_API_KEY), Discord alerts
    (DISCORD_WEBHOOK_URL) and email delivery (SMTP_* / EMAIL_* in app/delivery/settings.py `DeliverySettings`, on only
    when SMTP_HOST, EMAIL_FROM and EMAIL_POSTAL_ADDRESS are all set).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # SQLite works with zero setup; docker-compose points this at Postgres.
    database_url: str = "sqlite:///./data/undertow.db"
    data_dir: str = "./data"

    # SEC requires a descriptive User-Agent with contact info on every request.
    sec_user_agent: str = "undertow-dev contact@example.com"

    rss_feeds: dict[str, str] = DEFAULT_RSS_FEEDS
    edgar_enabled: bool = True

    # Optional, off unless both are set: Alpaca (Benzinga) news. Free with an Alpaca paper account (paper keys only).
    alpaca_api_key_id: str | None = None
    alpaca_api_secret_key: str | None = None

    # Optional, off when unset: LLM enrichment (summary, sentiment, event type, tickers).
    anthropic_api_key: str | None = None
    enrich_model: str = "claude-opus-5-5"
    enrich_max_per_cycle: int = 25
    filing_text_max_per_cycle: int = 40

    ingest_interval_seconds: int = 300
    # EDGAR gets its own fast loop for alerts (0 disables it and EDGAR joins the slow cycle)
    edgar_poll_seconds: int = 30

    # Optional, off when unset: Discord incoming-webhook URL for alerts (Server Settings > Integrations > Webhooks).
    # Keep it in .env.
    discord_webhook_url: str | None = None
    alert_min_severity: int = 2
    alert_sizes: list[str] = ["nano", "micro", "small"]
    alert_max_age_minutes: int = 15  # never alert on old filings (e.g. backlog after a restart)
    ingest_on_startup: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]
    # Site origin (the frontend, not the API) for links in the newsletter and emails (ticker pages, methodology,
    # track record). Keep it equal to the frontend's NEXT_PUBLIC_SITE_URL. The local default also keeps the admin
    # policy open on this machine (app/security.py is_local_origin). The API origin is http://localhost:8000.
    public_base_url: str = "http://localhost:3000"

    # Per-client sliding-window rate limits (app/security.py). 0 disables that tier.
    rate_limit_per_minute: int = Field(600, ge=0)  # every request except /api/stream and /api/health. Local default is
    # generous because every server-rendered page reaches the API from the one web container; prod compose pins 120.
    rate_limit_write_per_minute: int = Field(10, ge=0)  # POST/PUT/DELETE (incl. newsletter preview, subscribe)
    # Use X-Forwarded-For (right-most untrusted hop) only behind a reverse proxy you control
    # (not needed for local use).
    trust_proxy_headers: bool = False

    # Obsidian vault export (app/vault/AGENTS.md). Undertow writes plain Markdown only under <VAULT_DIR>/Undertow/
    # and never deletes anything. Compose sets VAULT_DIR=/app/vault and bind-mounts VAULT_HOST_DIR (default ./vault)
    # there; the container cwd is /app, so the default "./vault" is the same place.
    vault_enabled: bool = True
    vault_dir: str = "./vault"
    vault_lookback_days: int = 30  # signal filings newer than this get Signal notes (and their tickers Ticker notes)
    vault_export_minutes: int = 15  # how often the scheduler runs the export

    @property
    def alpaca_enabled(self) -> bool:
        return bool(self.alpaca_api_key_id and self.alpaca_api_secret_key)

    @property
    def enrich_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
