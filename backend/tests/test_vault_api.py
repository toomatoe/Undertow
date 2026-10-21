"""Vault API wiring: /api/vault/status|notes|export, vault_cycle throttle/lock/error handling, seal flag.

No lifespan (no `with TestClient`), in-memory SQLite, tmp vault/data dirs, network patched to fail."""

import threading
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, vault
from app.config import AdminSettings
from app.db import Base, engine
from app.main import app, state

client = TestClient(app)  # no `with`: the lifespan (network, scheduler, startup export) never runs

LOCAL = "http://localhost:3000"
PUBLIC = "https://undertow.example.org"

THESIS = """---
type: thesis
ticker: "[[ABCD]]"
updated: 2026-10-01
tags: [research]
---
# ABCD dilution thesis

Runway looks short; watching for an S-3.
"""

OTHER = """---
tags: undertow/thesis
ticker: WXYZ
updated: 2026-09-01
---
# WXYZ notes

Something else.
"""

INSIDE = """---
type: thesis
ticker: ABCD
---
# Machine note that must be ignored
"""


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def vault_env(monkeypatch, tmp_path):
    vdir, ddir = tmp_path / "vault", tmp_path / "data"
    ddir.mkdir()
    monkeypatch.setattr(main.settings, "vault_enabled", True)
    monkeypatch.setattr(main.settings, "vault_dir", str(vdir))
    monkeypatch.setattr(main.settings, "data_dir", str(ddir))
    monkeypatch.setattr(main.settings, "vault_export_minutes", 15)
    monkeypatch.setattr(state, "vault_last_run", None)
    monkeypatch.setattr(state, "vault_due", False)
    monkeypatch.setattr(state, "vault_notes_cache", {})
    monkeypatch.setattr(state, "paper_cache", {})

    def no_network(*a, **kw):
        raise httpx.ConnectError("network disabled in tests")

    monkeypatch.setattr(httpx, "get", no_network)
    monkeypatch.setattr(main.fundamentals, "company_profile", no_network)
    monkeypatch.setattr(main, "research_launch", AdminSettings(_env_file=None))
    monkeypatch.setattr(main.settings, "public_base_url", LOCAL)
    return vdir, ddir


def use(monkeypatch, public=LOCAL, **kw):
    monkeypatch.setattr(main, "research_launch", AdminSettings(_env_file=None, **kw))
    monkeypatch.setattr(main.settings, "public_base_url", public)


def counting_export(monkeypatch):
    calls = []

    def fake(session, **kw):
        calls.append(kw)
        return vault.ExportResult(started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc))

    monkeypatch.setattr(main.vault, "export_vault", fake)
    return calls


# --- status ---------------------------------------------------------------------------------------------------


def test_status_before_and_after_export(vault_env):
    vdir, _ = vault_env
    before = client.get("/api/vault/status")
    assert before.status_code == 200
    assert before.json() == {"enabled": True, "dir": str(vdir), "last_export_at": None, "last_result": None,
                             "conflicts": 0, "running": False}
    assert not vdir.exists()  # status never creates the vault

    res = main.vault_cycle(force=True)
    assert res is not None and res["errors"] == 0 and res["created"] > 0
    after = client.get("/api/vault/status").json()
    assert set(after) == {"enabled", "dir", "last_export_at", "last_result", "conflicts", "running"}
    assert after["last_export_at"] == res["finished_at"]
    last = after["last_result"]
    assert set(last) == {"created", "updated", "unchanged", "conflicts", "errors", "counts", "started_at", "finished_at"}
    assert last["created"] == res["created"] and last["errors"] == 0
    assert all(isinstance(v, int) for v in last["counts"].values())
    assert after["conflicts"] == 0 and after["running"] is False
    assert (vdir / "Undertow" / "index.md").is_file()


def test_status_reports_running_while_lock_held():
    with vault.EXPORT_LOCK:
        assert client.get("/api/vault/status").json()["running"] is True


def test_status_disabled(monkeypatch):
    monkeypatch.setattr(main.settings, "vault_enabled", False)
    assert client.get("/api/vault/status").json()["enabled"] is False


# --- notes ----------------------------------------------------------------------------------------------------


def write_notes(vdir):
    (vdir / "Research").mkdir(parents=True)
    (vdir / "Research" / "abcd-thesis.md").write_text(THESIS, encoding="utf-8")
    (vdir / "wxyz.md").write_text(OTHER, encoding="utf-8")
    (vdir / "Undertow" / "Tickers").mkdir(parents=True)
    (vdir / "Undertow" / "Tickers" / "ABCD.md").write_text(INSIDE, encoding="utf-8")


def test_notes_reads_thesis_outside_undertow_only(vault_env):
    vdir, _ = vault_env
    write_notes(vdir)
    r = client.get("/api/vault/notes?ticker=abcd")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["ticker"] == "ABCD"
    assert [n["path"] for n in body["notes"]] == ["Research/abcd-thesis.md"]
    note = body["notes"][0]
    assert set(note) == {"title", "path", "ticker", "updated", "tags", "excerpt"}
    assert note["title"] == "ABCD dilution thesis" and note["ticker"] == "ABCD"
    assert note["updated"] == "2026-10-01" and "research" in note["tags"]
    assert "S-3" in note["excerpt"]


def test_notes_ticker_filter(vault_env):
    vdir, _ = vault_env
    write_notes(vdir)
    assert [n["path"] for n in client.get("/api/vault/notes?ticker=WXYZ").json()["notes"]] == ["wxyz.md"]
    assert client.get("/api/vault/notes?ticker=NONE").json()["notes"] == []


def test_notes_cached_per_ticker(vault_env):
    vdir, _ = vault_env
    assert client.get("/api/vault/notes?ticker=ABCD").json()["notes"] == []
    write_notes(vdir)
    assert client.get("/api/vault/notes?ticker=ABCD").json()["notes"] == []  # cached for 60 s
    state.vault_notes_cache = {}
    assert len(client.get("/api/vault/notes?ticker=ABCD").json()["notes"]) == 1


def test_notes_when_vault_missing_or_disabled(monkeypatch):
    assert client.get("/api/vault/notes?ticker=ABCD").json() == {"enabled": True, "ticker": "ABCD", "notes": []}
    monkeypatch.setattr(main.settings, "vault_enabled", False)
    assert client.get("/api/vault/notes?ticker=ABCD").json() == {"enabled": False, "ticker": "ABCD", "notes": []}


@pytest.mark.parametrize("bad", ["", "../etc", "AB CD", "A" * 20, "$ABC", "ABC;rm", "1ABC"])
def test_notes_rejects_junk_ticker(bad):
    assert client.get("/api/vault/notes", params={"ticker": bad}).status_code in (400, 422)


def test_notes_requires_ticker():
    assert client.get("/api/vault/notes").status_code == 422


@pytest.mark.parametrize("ok", ["BRK.B", "BF-A", "abcd"])
def test_notes_accepts_class_suffix(ok):
    assert client.get("/api/vault/notes", params={"ticker": ok}).status_code == 200


# --- POST /api/vault/export -----------------------------------------------------------------------------------


def test_export_needs_bearer_token_when_set(monkeypatch):
    calls = counting_export(monkeypatch)
    use(monkeypatch, public=PUBLIC, admin_token="s3cret")
    r = client.post("/api/vault/export")
    assert r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer"
    assert client.post("/api/vault/export", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert calls == []
    r = client.post("/api/vault/export", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and len(calls) == 1
    assert set(r.json()) == {"enabled", "dir", "last_export_at", "last_result", "conflicts", "running"}


def test_export_403_when_policy_disallows(monkeypatch):
    calls = counting_export(monkeypatch)
    use(monkeypatch, public=PUBLIC)  # no token, no flag, public origin
    assert client.post("/api/vault/export").status_code == 403
    use(monkeypatch, public=LOCAL, mutations_enabled=False)
    assert client.post("/api/vault/export").status_code == 403
    assert calls == []


def test_export_localhost_policy_runs_real_export(vault_env):
    vdir, _ = vault_env
    r = client.post("/api/vault/export")
    assert r.status_code == 200
    body = r.json()
    assert body["last_result"] is not None and body["last_result"]["created"] > 0
    assert body["running"] is False and body["last_export_at"]
    assert (vdir / "Undertow" / "index.md").is_file()


def test_export_is_forced_past_throttle(monkeypatch):
    calls = counting_export(monkeypatch)
    assert main.vault_cycle() is not None
    assert client.post("/api/vault/export").status_code == 200
    assert len(calls) == 2


def test_export_409_when_disabled(monkeypatch):
    calls = counting_export(monkeypatch)
    monkeypatch.setattr(main.settings, "vault_enabled", False)
    r = client.post("/api/vault/export")
    assert r.status_code == 409 and "disabled" in r.json()["detail"]
    assert calls == []


def test_export_409_when_running(monkeypatch):
    calls = counting_export(monkeypatch)
    with vault.EXPORT_LOCK:
        r = client.post("/api/vault/export")
    assert r.status_code == 409 and r.json()["detail"]
    assert calls == []


def test_export_admin_check_runs_before_409(monkeypatch):
    monkeypatch.setattr(main.settings, "vault_enabled", False)
    use(monkeypatch, public=PUBLIC, admin_token="s3cret")
    assert client.post("/api/vault/export").status_code == 401


# --- vault_cycle ----------------------------------------------------------------------------------------------


def test_vault_cycle_disabled_returns_none(monkeypatch):
    calls = counting_export(monkeypatch)
    monkeypatch.setattr(main.settings, "vault_enabled", False)
    assert main.vault_cycle(force=True) is None
    assert calls == []


def test_vault_cycle_swallows_export_exception(monkeypatch):
    def boom(session, **kw):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(main.vault, "export_vault", boom)
    assert main.vault_cycle(force=True) is None
    assert not vault.EXPORT_LOCK.locked()  # released after the failure
    r = client.post("/api/vault/export")
    assert r.status_code == 500 and "log" in r.json()["detail"]


def test_vault_cycle_throttle(monkeypatch):
    calls = counting_export(monkeypatch)
    assert main.vault_cycle() is not None  # first run: nothing ran before
    assert main.vault_cycle() is None  # within vault_export_minutes: skipped
    assert len(calls) == 1
    assert main.vault_cycle(force=True) is not None
    assert len(calls) == 2
    state.vault_last_run -= 16 * 60  # window elapsed
    assert main.vault_cycle() is not None
    assert len(calls) == 3


def test_vault_cycle_skips_when_lock_held(monkeypatch):
    calls = counting_export(monkeypatch)
    with vault.EXPORT_LOCK:
        assert main.vault_cycle(force=True) is None
    assert calls == []


def test_vault_cycle_passes_settings_and_callables(monkeypatch, vault_env):
    vdir, ddir = vault_env
    calls = counting_export(monkeypatch)
    monkeypatch.setattr(main.settings, "vault_lookback_days", 7)
    main.vault_cycle(force=True)
    kw = calls[0]
    assert kw["vault_dir"] == str(vdir) and kw["data_dir"] == str(ddir) and kw["lookback_days"] == 7
    assert kw["study_files"] == main.STUDY_FILES
    assert kw["paper_fn"]() is None  # nothing cached: no recompute
    assert kw["evidence_fn"] is main.vault_evidence


def test_cached_paper_summary_prefers_default_params(monkeypatch):
    today = date(2026, 10, 21)
    monkeypatch.setattr(state, "paper_cache", {
        (today, True, 20): (5.0, {"which": "hedged"}),
        (today, False, 20): (1.0, {"which": "default"}),
    })
    assert main.cached_paper_summary() == {"which": "default"}
    monkeypatch.setattr(state, "paper_cache", {(today, True, 5): (1.0, {"which": "only"})})
    assert main.cached_paper_summary() == {"which": "only"}


def test_vault_evidence_uses_main_study_rows(monkeypatch):
    from app.schemas import Evidence

    ev = Evidence(signal="auditor_change", bucket="nano", n=30, horizon_days=20, mean_abnormal=-0.08,
                  mean_net=0.05, t_stat=-3.1, significant=True)
    monkeypatch.setattr(state, "evidence", {("auditor_change", "nano"): ev})
    assert main.vault_evidence("auditor_change", "nano") is ev
    assert main.vault_evidence("auditor_change", "micro") is None


def test_seal_cycle_new_days_bypass_throttle(monkeypatch):
    calls = counting_export(monkeypatch)
    assert main.vault_cycle() is not None
    assert main.vault_cycle() is None  # throttled

    monkeypatch.setattr(state, "sealed_through", None)
    monkeypatch.setattr(main.chain, "seal_through", lambda session, data_dir, through, now=None: [{"day": through.isoformat()}])
    main.seal_cycle(datetime(2026, 10, 19, 0, 10, tzinfo=timezone.utc))
    assert state.vault_due is True
    assert main.vault_cycle() is not None  # runs despite the 15-minute window
    assert state.vault_due is False
    assert main.vault_cycle() is None
    assert len(calls) == 2


def test_seal_cycle_without_new_days_keeps_throttle(monkeypatch):
    monkeypatch.setattr(state, "sealed_through", None)
    monkeypatch.setattr(main.chain, "seal_through", lambda session, data_dir, through, now=None: [])
    main.seal_cycle(datetime(2026, 10, 19, 0, 10, tzinfo=timezone.utc))
    assert state.vault_due is False


def test_concurrent_cycles_never_overlap(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow(session, **kw):
        calls.append(1)
        started.set()
        release.wait(5)
        return vault.ExportResult(started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc))

    monkeypatch.setattr(main.vault, "export_vault", slow)
    t = threading.Thread(target=main.vault_cycle, args=(True,))
    t.start()
    assert started.wait(5)
    assert main.vault_cycle(force=True) is None  # second run skipped while the first holds the lock
    assert client.post("/api/vault/export").status_code == 409
    release.set()
    t.join(5)
    assert len(calls) == 1
