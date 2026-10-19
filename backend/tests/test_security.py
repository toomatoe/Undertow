"""Admin policy on every mutating endpoint, and the rate limiter (injected clock, no sleeping)."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.config import AdminSettings
from app.db import Base, engine
from app.security import RateLimiter, RateLimitMiddleware, SlidingWindow, admin_policy, client_key

client = TestClient(main.app)  # no `with`: the lifespan (network) never runs
PUBLIC = "https://quantdesk.example.com"
LOCAL = "http://localhost:3000"


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def no_ingest(monkeypatch):
    calls = []

    async def fake_ingest():
        calls.append(True)
        return {"stub": 1}

    monkeypatch.setattr(main, "ingest_once", fake_ingest)
    monkeypatch.setattr(main.state, "alerter", None)  # alerts/test -> 503 once past the admin gate
    return calls


def use(monkeypatch, public=LOCAL, **kw):
    monkeypatch.setattr(main, "research_launch", AdminSettings(_env_file=None, **kw))
    monkeypatch.setattr(main.settings, "public_base_url", public)


def mutations(headers=None):
    """Status codes of every protected non-research endpoint, in a fixed order."""
    h = headers or {}
    return [
        client.put("/api/watchlist/ABC", headers=h).status_code,
        client.delete("/api/watchlist/ABC", headers=h).status_code,
        client.post("/api/ingest", headers=h).status_code,
        client.post("/api/alerts/test", headers=h).status_code,
    ]


ALLOWED = [200, 200, 200, 503]  # alerts/test: 503 "Alerter not started" means the gate let it through


# --- Admin policy ------------------------------------------------------------------------------


def test_local_origin_default_allows_mutations(monkeypatch, no_ingest):
    use(monkeypatch)
    assert mutations() == ALLOWED
    assert no_ingest == [True]


@pytest.mark.parametrize("public", [PUBLIC, "http://192.168.1.20:3000", "https://localhost.example.com"])
def test_public_origin_without_token_is_403(monkeypatch, no_ingest, public):
    use(monkeypatch, public=public)
    assert mutations() == [403] * 4
    assert no_ingest == []
    assert "ADMIN_TOKEN" in client.post("/api/ingest").json()["detail"]


@pytest.mark.parametrize("public", ["http://127.0.0.1:3000", "http://[::1]:3000", "http://app.localhost"])
def test_other_local_origins_allowed(monkeypatch, public):
    use(monkeypatch, public=public)
    assert mutations() == ALLOWED


def test_token_required_when_set(monkeypatch, no_ingest):
    use(monkeypatch, public=PUBLIC, admin_token="s3cret")
    assert mutations() == [401] * 4
    r = client.put("/api/watchlist/ABC")
    assert r.headers["www-authenticate"] == "Bearer" and "Admin token required" in r.json()["detail"]
    assert no_ingest == []
    assert mutations({"Authorization": "Bearer s3cret"}) == ALLOWED
    assert no_ingest == [True]


@pytest.mark.parametrize("header", ["Bearer wrong", "s3cret", "Basic s3cret", "Bearer s3cret-and-more", "Bearer "])
def test_wrong_token_is_401(monkeypatch, header):
    use(monkeypatch, admin_token="s3cret")  # even on a local origin, a token wins
    assert mutations({"Authorization": header}) == [401] * 4


def test_token_wins_over_disable_flags(monkeypatch):
    use(monkeypatch, public=PUBLIC, admin_token="s3cret", mutations_enabled=False)
    assert mutations({"Authorization": "Bearer s3cret"}) == ALLOWED


def test_mutations_flag(monkeypatch):
    use(monkeypatch, public=PUBLIC, mutations_enabled=True)
    assert mutations() == ALLOWED
    use(monkeypatch, public=LOCAL, mutations_enabled=False)
    assert mutations() == [403] * 4


def test_research_flag_scoped_to_research_and_falls_back_to_mutations_flag():
    cfg = AdminSettings(_env_file=None, research_jobs_enabled=False)
    assert admin_policy(cfg, LOCAL, "research").enabled is False
    assert admin_policy(cfg, LOCAL, "mutations").enabled is True
    cfg = AdminSettings(_env_file=None, mutations_enabled=True)
    assert admin_policy(cfg, PUBLIC, "research").enabled is True
    cfg = AdminSettings(_env_file=None, mutations_enabled=True, research_jobs_enabled=False)
    assert admin_policy(cfg, PUBLIC, "research").enabled is False


def test_research_admin_token_alias(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("RESEARCH_ADMIN_TOKEN", "old-name")
    cfg = AdminSettings(_env_file=None)
    assert cfg.admin_token.get_secret_value() == "old-name"
    assert cfg.research_admin_token.get_secret_value() == "old-name"
    monkeypatch.setenv("ADMIN_TOKEN", "new-name")
    assert AdminSettings(_env_file=None).admin_token.get_secret_value() == "new-name"  # ADMIN_TOKEN wins
    # The old name protects every mutation, not only research launches
    use(monkeypatch, public=PUBLIC, research_admin_token="old-name")
    assert mutations() == [401] * 4
    assert mutations({"Authorization": "Bearer old-name"}) == ALLOWED


def test_blank_env_values_mean_unset(monkeypatch):
    for name in ("ADMIN_TOKEN", "RESEARCH_ADMIN_TOKEN", "MUTATIONS_ENABLED", "RESEARCH_JOBS_ENABLED"):
        monkeypatch.setenv(name, "")
    cfg = AdminSettings(_env_file=None)
    assert cfg.admin_token is None and cfg.mutations_enabled is None and cfg.research_jobs_enabled is None
    monkeypatch.setenv("MUTATIONS_ENABLED", "false")
    assert AdminSettings(_env_file=None).mutations_enabled is False


def test_whitespace_token_is_no_token(monkeypatch):
    use(monkeypatch, public=PUBLIC, admin_token="   ")
    assert mutations() == [403] * 4


def test_status_reports_protection_without_leaking_token(monkeypatch):
    use(monkeypatch, public=PUBLIC, admin_token="s3cret")
    body = client.get("/api/status").json()
    assert body["admin"] == {"protected": True, "mutations_enabled": True}
    assert "s3cret" not in json.dumps(body)
    use(monkeypatch, public=PUBLIC)
    assert client.get("/api/status").json()["admin"] == {"protected": False, "mutations_enabled": False}
    use(monkeypatch)
    assert client.get("/api/status").json()["admin"] == {"protected": False, "mutations_enabled": True}


def test_reads_stay_open_on_protected_server(monkeypatch):
    use(monkeypatch, public=PUBLIC, admin_token="s3cret")
    assert client.get("/api/watchlist").status_code == 200
    assert client.get("/api/health").status_code == 200


# --- Rate limiter ------------------------------------------------------------------------------


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def mini_app(limiter):
    app = FastAPI()

    @app.get("/api/stream")
    def stream():
        return {"sse": True}

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/x")
    def read():
        return {"r": True}

    @app.post("/api/x")
    def write():
        return {"w": True}

    app.add_middleware(RateLimitMiddleware, get_limiter=lambda: limiter)
    return app


def test_limiter_returns_429_with_retry_after_and_window_slides():
    clock = Clock()
    c = TestClient(mini_app(RateLimiter(3, 10, clock=clock)), client=("203.0.113.5", 4000))
    for _ in range(3):  # hits at t=1000, 1010, 1020
        assert c.get("/api/x").status_code == 200
        clock.t += 10
    r = c.get("/api/x")  # t=1030
    assert r.status_code == 429
    assert r.headers["retry-after"] == "30"  # the first hit leaves the window at t=1060
    assert "Too many requests" in r.json()["detail"]
    clock.t += 29.5
    assert c.get("/api/x").status_code == 429  # rejected requests are not counted
    clock.t += 1
    assert c.get("/api/x").status_code == 200  # t=1060.5: one slot freed
    r = c.get("/api/x")
    assert r.status_code == 429 and r.headers["retry-after"] == "10"  # next expiry: the t=1010 hit


def test_write_tier_is_separate_and_stricter():
    clock = Clock()
    c = TestClient(mini_app(RateLimiter(100, 2, clock=clock)), client=("203.0.113.5", 4000))
    assert [c.post("/api/x").status_code for _ in range(3)] == [200, 200, 429]
    assert c.get("/api/x").status_code == 200  # reads still allowed
    clock.t += 61
    assert c.post("/api/x").status_code == 200


def test_sse_health_and_preflight_are_exempt():
    clock = Clock()
    c = TestClient(mini_app(RateLimiter(1, 1, clock=clock)), client=("203.0.113.5", 4000))
    assert c.get("/api/x").status_code == 200
    assert c.get("/api/x").status_code == 429
    assert all(c.get("/api/stream").status_code == 200 for _ in range(5))
    assert all(c.get("/api/health").status_code == 200 for _ in range(5))
    assert c.options("/api/x").status_code != 429


def test_zero_disables_a_tier():
    c = TestClient(mini_app(RateLimiter(0, 0, clock=Clock())), client=("203.0.113.5", 4000))
    assert all(c.post("/api/x").status_code == 200 for _ in range(30))


def test_clients_are_limited_separately():
    limiter = RateLimiter(1, 1, clock=Clock())
    app = mini_app(limiter)
    assert TestClient(app, client=("203.0.113.5", 1)).get("/api/x").status_code == 200
    assert TestClient(app, client=("203.0.113.6", 1)).get("/api/x").status_code == 200
    assert TestClient(app, client=("203.0.113.5", 2)).get("/api/x").status_code == 429


def test_forwarded_for_ignored_unless_trusted():
    app = mini_app(RateLimiter(1, 1, clock=Clock(), trust_proxy=False))
    c = TestClient(app, client=("10.0.0.2", 1))
    assert c.get("/api/x", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    # A different spoofed header does not buy a fresh bucket
    assert c.get("/api/x", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 429


def test_forwarded_for_used_behind_trusted_proxy():
    app = mini_app(RateLimiter(1, 1, clock=Clock(), trust_proxy=True))
    proxy = TestClient(app, client=("10.0.0.2", 1))  # private peer = our reverse proxy
    assert proxy.get("/api/x", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert proxy.get("/api/x", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200
    # The client controls the left part of the chain: only the right-most untrusted hop counts
    assert proxy.get("/api/x", headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.1, 172.18.0.5"}).status_code == 429


def test_client_key_rules():
    def scope(peer, xff=None):
        return {"client": (peer, 1), "headers": [(b"x-forwarded-for", xff.encode())] if xff else []}

    assert client_key(scope("203.0.113.9", "198.51.100.1"), trust_proxy=False) == "203.0.113.9"
    assert client_key(scope("10.0.0.2", "6.6.6.6, 198.51.100.1, 10.0.0.9"), trust_proxy=True) == "198.51.100.1"
    # A public peer is not our proxy: its X-Forwarded-For is ignored even when proxies are trusted
    assert client_key(scope("203.0.113.9", "198.51.100.1"), trust_proxy=True) == "203.0.113.9"
    assert client_key(scope("10.0.0.2", "10.0.0.3, 10.0.0.4"), trust_proxy=True) == "10.0.0.3"
    assert client_key(scope("10.0.0.2"), trust_proxy=True) == "10.0.0.2"
    assert client_key({"client": None, "headers": []}, trust_proxy=False) == "unknown"
    assert client_key(scope("testclient"), trust_proxy=False) is None
    assert len(client_key(scope("10.0.0.2", "x" * 500), trust_proxy=True)) == 64


def test_memory_is_bounded():
    clock = Clock()
    w = SlidingWindow(limit=5, window=60, max_keys=100, clock=clock)
    for i in range(1000):
        w.record(f"k{i}", clock.t)
    assert len(w.hits) == 100
    assert "k999" in w.hits and "k0" not in w.hits  # least recently seen dropped first
    for _ in range(50):
        w.record("busy", clock.t)
    assert len(w.hits["busy"]) == 5  # per-key log capped at the limit
    clock.t += 61
    w.record("fresh", clock.t)
    assert list(w.hits) == ["fresh"]  # idle keys evicted


def test_main_app_limits_real_clients_and_exempts_test_client(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(main, "rate_limiter", RateLimiter(2, 1, clock=clock))
    c = TestClient(main.app, client=("203.0.113.77", 1))
    assert [c.get("/api/signals/catalog").status_code for _ in range(3)] == [200, 200, 429]
    r = c.get("/api/signals/catalog", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"  # CORS wraps the 429
    assert c.get("/api/health").status_code == 200
    assert client.get("/api/signals/catalog").status_code == 200  # Starlette's test client peer is exempt
    clock.t += 60
    assert c.get("/api/signals/catalog").status_code == 200


def test_subscribe_and_preview_use_write_tier(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(main, "rate_limiter", RateLimiter(100, 1, clock=clock))
    c = TestClient(main.app, client=("203.0.113.78", 1))
    assert c.post("/api/subscribe", json={"email": "a@example.com"}).status_code != 429
    assert c.post("/api/subscribe", json={"email": "a@example.com"}).status_code == 429
    assert c.post("/api/newsletter/preview").status_code == 429
