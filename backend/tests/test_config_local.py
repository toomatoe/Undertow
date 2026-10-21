"""Zero-configuration local defaults: a clean environment gives a localhost site, every integration off, open admin.

Undertow is local-only. PUBLIC_BASE_URL is the SITE origin (frontend, :3000), not the API origin (:8000).
No network: nothing here builds a client or sends anything.
"""

import pytest

from app.alerts.service import Alerter
from app.config import Settings
from app.delivery.settings import DeliverySettings
from app.security import admin_policy, is_local_origin

# Every env var that could switch an integration on or change the defaults under test.
ENV_VARS = [
    "PUBLIC_BASE_URL",
    "CORS_ORIGINS",
    "ADMIN_TOKEN",
    "RESEARCH_ADMIN_TOKEN",
    "RESEARCH_JOBS_ENABLED",
    "MUTATIONS_ENABLED",
    "DISCORD_WEBHOOK_URL",
    "ALPACA_API_KEY_ID",
    "ALPACA_API_SECRET_KEY",
    "ANTHROPIC_API_KEY",
    "TRUST_PROXY_HEADERS",
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "EMAIL_FROM",
    "EMAIL_REPLY_TO",
    "EMAIL_POSTAL_ADDRESS",
    "EMAIL_LINK_BASE_URL",
    "EMAIL_TOKEN_SECRET",
]


@pytest.fixture
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def make_settings() -> Settings:
    # _env_file=None: ignore any developer .env so only code defaults apply.
    return Settings(_env_file=None)


def test_site_origin_defaults_to_localhost_3000(clean_env):
    s = make_settings()
    assert s.public_base_url == "http://localhost:3000"
    # Site origin, not the API origin.
    assert ":8000" not in s.public_base_url
    assert s.cors_origins == ["http://localhost:3000"]
    assert s.trust_proxy_headers is False


def test_optional_integrations_are_off(clean_env):
    s = make_settings()
    assert s.discord_webhook_url is None
    assert s.alpaca_enabled is False
    assert s.enrich_enabled is False
    assert s.admin_token is None


def test_discord_alerts_disabled_by_default(clean_env):
    calls = []
    alerter = Alerter(make_settings(), evidence_for=lambda _a: [], post=lambda *a, **k: calls.append((a, k)))
    assert alerter.channel == "none"
    assert calls == []


def test_email_delivery_disabled_by_default(clean_env):
    d = DeliverySettings(_env_file=None)
    assert d.smtp_host is None
    assert d.email_from is None
    assert d.email_postal_address is None
    assert d.enabled is False


def test_admin_policy_treats_default_as_local(clean_env):
    s = make_settings()
    assert is_local_origin(s.public_base_url)
    for scope in ("mutations", "research"):
        policy = admin_policy(s, s.public_base_url, scope)
        assert policy.enabled is True
        assert policy.protected is False


def test_non_local_site_closes_admin_policy(clean_env, monkeypatch):
    # Guard rail: if someone points PUBLIC_BASE_URL at a public origin, changes are closed by default.
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://undertow.invalid")
    s = make_settings()
    assert not is_local_origin(s.public_base_url)
    assert admin_policy(s, s.public_base_url, "mutations").enabled is False


def test_vault_export_defaults(clean_env, monkeypatch):
    # Obsidian vault export: on by default, writes under ./vault (/app/vault in compose), 30-day window, every 15 min.
    for name in ("VAULT_ENABLED", "VAULT_DIR", "VAULT_LOOKBACK_DAYS", "VAULT_EXPORT_MINUTES"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    s = make_settings()
    assert s.vault_enabled is True
    assert s.vault_dir == "./vault"
    assert s.vault_lookback_days == 30
    assert s.vault_export_minutes == 15


def test_vault_settings_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("VAULT_ENABLED", "false")
    monkeypatch.setenv("VAULT_DIR", "/app/vault")
    s = make_settings()
    assert s.vault_enabled is False
    assert s.vault_dir == "/app/vault"
