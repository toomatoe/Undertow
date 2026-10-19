"""Settings of the live Form 4 forward test (app.insiders.live).

Lives here, not in app.config.Settings, because config.py is owned by another work item; same pattern as
app.delivery.settings. It should move into app.config.Settings later (same env name).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class InsiderLiveSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # INSIDER_LIVE_ENABLED: the live insider-cluster forward test runs inside the fast EDGAR poller when this
    # is true AND EDGAR_ENABLED is true. Set false to stop all Form 4 requests.
    insider_live_enabled: bool = True


def get_live_settings() -> InsiderLiveSettings:
    """Not cached, so tests can monkeypatch env (or this function) per test."""
    return InsiderLiveSettings()
