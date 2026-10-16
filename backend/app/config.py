from functools import lru_cache

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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite works with zero setup; docker-compose points this at Postgres.
    database_url: str = "sqlite:///./data/quantdesk.db"
    data_dir: str = "./data"

    # SEC requires a descriptive User-Agent with contact info on every request.
    sec_user_agent: str = "quantdesk-dev contact@example.com"

    rss_feeds: dict[str, str] = DEFAULT_RSS_FEEDS
    edgar_enabled: bool = True

    # Optional: Alpaca (Benzinga) news. Free with an Alpaca paper account.
    alpaca_api_key_id: str | None = None
    alpaca_api_secret_key: str | None = None

    # Optional: LLM enrichment (summary, sentiment, event type, tickers).
    anthropic_api_key: str | None = None
    enrich_model: str = "claude-opus-5-5"
    enrich_max_per_cycle: int = 25
    filing_text_max_per_cycle: int = 40

    ingest_interval_seconds: int = 300
    # EDGAR gets its own fast loop for alerts (0 disables it and EDGAR joins the slow cycle)
    edgar_poll_seconds: int = 30

    # Alerts: Discord incoming-webhook URL (Server Settings > Integrations > Webhooks). Keep it in .env.
    discord_webhook_url: str | None = None
    alert_min_severity: int = 2
    alert_sizes: list[str] = ["nano", "micro", "small"]
    alert_max_age_minutes: int = 15  # never alert on old filings (e.g. backlog after a restart)
    ingest_on_startup: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]
    # Public site URL used for links in the newsletter (ticker pages, methodology, track record)
    public_base_url: str = "http://localhost:3000"

    @property
    def alpaca_enabled(self) -> bool:
        return bool(self.alpaca_api_key_id and self.alpaca_api_secret_key)

    @property
    def enrich_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
