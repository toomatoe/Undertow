"""Email delivery settings. Everything is optional: without SMTP_HOST, EMAIL_FROM and EMAIL_POSTAL_ADDRESS the
feature is off (POST /api/subscribe returns 503, scheduler hooks do nothing).

These fields live here, not in app.config.Settings, only because this module was built in parallel with the
config owner. They should move into app.config.Settings later (same env names).
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import get_settings


class DeliverySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True  # port 465 uses implicit TLS instead (SMTP_SSL)
    smtp_timeout_seconds: float = 20.0

    email_from: str | None = None  # e.g. "QuantDesk <radar@example.com>"
    email_reply_to: str | None = None  # also used as the mailto: List-Unsubscribe target
    email_postal_address: str | None = None  # CAN-SPAM: a valid physical postal address, printed in every footer

    # ET hour on day D at which the digest for the finished day D-1 goes out (default: before the 09:30 open).
    email_daily_digest_hour_et: int = Field(default=7, ge=0, le=23)
    email_max_per_run: int = 500

    # Public origin where the API's /api/... routes are reachable (confirm/unsubscribe links).
    # Defaults to PUBLIC_BASE_URL, which works when the site proxies /api to the backend.
    email_link_base_url: str | None = None
    # Key for deriving stable per-subscriber unsubscribe tokens. If unset, a random key is created once at
    # {DATA_DIR}/delivery/token_key. Changing it invalidates every unsubscribe link already sent.
    email_token_secret: SecretStr | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.smtp_host and self.email_from and self.email_postal_address)

    @property
    def link_base(self) -> str:
        return (self.email_link_base_url or get_settings().public_base_url).rstrip("/")

    @property
    def site_base(self) -> str:
        return get_settings().public_base_url.rstrip("/")


def get_delivery_settings() -> DeliverySettings:
    """Not cached, so tests can monkeypatch this function (or env) per test."""
    return DeliverySettings()
