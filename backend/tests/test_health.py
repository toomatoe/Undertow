"""Deep health: statuses from stubbed state, the EDGAR-hours rule, uptime.jsonl trimming and history math."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import health, main
from app.db import Base, engine
from app.health import HealthInputs, evaluate

client = TestClient(main.app)
# Wednesday 2026-10-14 15:00 UTC = 11:00 ET (EDT, UTC-4)
WED_11_ET = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def fresh(now=WED_11_ET, **kw) -> HealthInputs:
    base = dict(db_ok=True, last_ingest_ok=now - timedelta(minutes=2), last_edgar_poll=now - timedelta(seconds=20),
                last_halts_poll=now - timedelta(seconds=20), edgar_poll_seconds=30, ingest_interval_seconds=300,
                journal_marked=now.date(), newsletter_latest={"id": "2026-W41", "week_end": "2026-10-11"},
                alerts_channel="discord", alerts_last={"status": "sent", "reason": None, "at": now.isoformat()},
                email_enabled=True, research_active=None)
    base.update(kw)
    return HealthInputs(**base)


def test_all_fresh_is_ok():
    d = evaluate(fresh(), WED_11_ET)
    assert d["status"] == "ok"
    assert set(d["components"]) == {"db", "ingest", "edgar_poller", "halts_poller", "journal", "newsletter", "alerts",
                                    "email", "research_job"}
    assert all(c["status"] == "ok" for c in d["components"].values())
    assert d["components"]["ingest"]["age_seconds"] == 120
    assert d["components"]["newsletter"]["latest_issue"] == "2026-W41"
    assert d["thresholds"]["ingest_stale_seconds"] == 900 and d["thresholds"]["edgar_stale_seconds"] == 300


def test_db_failure_is_down():
    d = evaluate(fresh(db_ok=False, db_error="OperationalError"), WED_11_ET)
    assert d["status"] == "down"
    assert d["components"]["db"] == {"status": "down", "detail": "OperationalError"}
    assert d["components"]["ingest"]["status"] == "unknown"


def test_ingest_stale_over_three_intervals_is_degraded():
    at_limit = evaluate(fresh(last_ingest_ok=WED_11_ET - timedelta(seconds=900)), WED_11_ET)
    assert at_limit["status"] == "ok"
    stale = evaluate(fresh(last_ingest_ok=WED_11_ET - timedelta(seconds=901)), WED_11_ET)
    assert stale["status"] == "degraded" and stale["components"]["ingest"]["status"] == "degraded"
    never = evaluate(fresh(last_ingest_ok=None), WED_11_ET)
    assert never["status"] == "degraded"
    # Threshold follows INGEST_INTERVAL_SECONDS
    assert evaluate(fresh(ingest_interval_seconds=600, last_ingest_ok=WED_11_ET - timedelta(seconds=1500)), WED_11_ET)["status"] == "ok"


def test_naive_timestamps_are_utc():
    naive = (WED_11_ET - timedelta(minutes=1)).replace(tzinfo=None)  # SQLite drops tzinfo
    assert evaluate(fresh(last_ingest_ok=naive), WED_11_ET)["components"]["ingest"]["age_seconds"] == 60


@pytest.mark.parametrize("now,expected", [
    (datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc), "degraded"),   # Wed 11:00 ET
    (datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc), "degraded"),   # Wed 06:00 ET (window opens)
    (datetime(2026, 10, 14, 9, 59, tzinfo=timezone.utc), "ok"),         # Wed 05:59 ET
    (datetime(2026, 10, 15, 1, 59, tzinfo=timezone.utc), "degraded"),   # Wed 21:59 ET
    (datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc), "ok"),          # Wed 22:00 ET (window closed)
    (datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc), "ok"),         # Saturday 11:00 ET
    (datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc), "ok"),         # Sunday 11:00 ET
    (datetime(2026, 12, 16, 16, 0, tzinfo=timezone.utc), "degraded"),   # Wed 11:00 EST (UTC-5)
    (datetime(2026, 12, 16, 10, 30, tzinfo=timezone.utc), "ok"),        # Wed 05:30 EST
])
def test_edgar_stale_rule_only_in_edgar_hours(now, expected):
    inp = fresh(now, last_edgar_poll=now - timedelta(minutes=10), last_halts_poll=now)
    d = evaluate(inp, now)
    assert d["components"]["edgar_poller"]["status"] == expected
    assert d["status"] == expected


def test_edgar_five_minute_threshold():
    assert evaluate(fresh(last_edgar_poll=WED_11_ET - timedelta(seconds=300)), WED_11_ET)["status"] == "ok"
    assert evaluate(fresh(last_edgar_poll=WED_11_ET - timedelta(seconds=301)), WED_11_ET)["status"] == "degraded"
    assert evaluate(fresh(last_edgar_poll=None), WED_11_ET)["status"] == "degraded"


def test_fast_poll_disabled_is_not_degraded():
    d = evaluate(fresh(edgar_poll_seconds=0, last_edgar_poll=None, last_halts_poll=None), WED_11_ET)
    assert d["components"]["edgar_poller"]["status"] == "disabled"
    assert d["status"] == "ok"


def test_informational_components_never_change_overall():
    d = evaluate(fresh(last_halts_poll=None, alerts_last={"status": "failed", "reason": "http_500", "at": "x"},
                       journal_marked=None, newsletter_latest=None, email_enabled=False, alerts_channel="discord",
                       research_active="event_study_oos"), WED_11_ET)
    c = d["components"]
    assert c["halts_poller"]["status"] == "degraded" and c["alerts"]["status"] == "degraded"
    assert c["journal"]["status"] == "unknown" and c["newsletter"]["status"] == "unknown"
    assert c["email"] == {"status": "disabled", "enabled": False, "detail": "SMTP not configured"}
    assert c["research_job"]["active"] == "event_study_oos"
    assert d["status"] == "ok"
    assert evaluate(fresh(alerts_channel="none"), WED_11_ET)["components"]["alerts"]["status"] == "disabled"


# --- uptime.jsonl ----------------------------------------------------------------------------


def snap(t: datetime, overall="ok", **comps):
    c = {"db": "ok", "ingest": "ok", "edgar_poller": "ok"}
    c.update(comps)
    return {"t": t.isoformat(), "s": overall, "c": c}


def write_lines(tmp_path, rows, extra=""):
    (tmp_path / health.UPTIME_FILE).write_text("".join(json.dumps(r) + "\n" for r in rows) + extra)


def test_append_and_trim_keeps_last_30_days(tmp_path):
    now = WED_11_ET
    old = [snap(now - timedelta(days=d)) for d in (35, 31.5, 30.5, 10)]
    write_lines(tmp_path, old)
    health.append_snapshot(str(tmp_path), evaluate(fresh(), now), now=now)
    rows = health.read_snapshots(str(tmp_path))
    assert len(rows) == 2  # oldest line > 31 days old triggers the rewrite, which keeps the last 30 days
    assert rows[0]["t"] == old[3]["t"]
    assert rows[-1]["t"] == now.isoformat() and rows[-1]["c"]["ingest"] == "ok"


def test_trim_waits_for_a_day_of_slack(tmp_path):
    now = WED_11_ET
    write_lines(tmp_path, [snap(now - timedelta(days=30.9)), snap(now - timedelta(days=1))])
    health.append_snapshot(str(tmp_path), evaluate(fresh(), now), now=now)
    assert len(health.read_snapshots(str(tmp_path))) == 3  # oldest is not yet 31 days old: no rewrite
    assert not list(tmp_path.glob("*.tmp"))


def test_torn_and_foreign_lines_are_skipped(tmp_path):
    write_lines(tmp_path, [snap(WED_11_ET), {"t": "nope", "s": "ok", "c": {}}, {"x": 1}], extra='{"t": "2026-10-')
    assert len(health.read_snapshots(str(tmp_path))) == 1
    assert health.read_snapshots(str(tmp_path / "missing")) == []


def test_history_math():
    now = WED_11_ET
    t0 = now - timedelta(hours=3)
    rows = [
        snap(t0),
        snap(t0 + timedelta(hours=1), "degraded", edgar_poller="degraded"),
        snap(t0 + timedelta(hours=2), "ok", journal="unknown"),
        snap(t0 + timedelta(hours=2, minutes=30), "ok", ingest="disabled"),
        snap(now - timedelta(days=8)),  # outside a 7-day window
    ]
    h = health.history(rows, 7, now)
    assert h["samples"] == 4
    assert h["uptime_pct"] == 75.0
    assert h["components"]["edgar_poller"] == {"uptime_pct": 75.0, "samples": 4}
    assert h["components"]["ingest"] == {"uptime_pct": 100.0, "samples": 4}  # disabled counts as up
    assert "journal" not in h["components"]  # unknown samples are not counted
    assert len(h["daily"]) == 7 and h["daily"][-1] == {"day": "2026-10-14", "uptime_pct": 75.0, "samples": 4}
    assert h["daily"][0]["samples"] == 0 and h["daily"][0]["uptime_pct"] is None
    overall = [i for i in h["incidents"] if i["component"] == "overall"]
    assert overall == [  # newest first
        {"at": rows[2]["t"], "component": "overall", "from": "degraded", "to": "ok"},
        {"at": rows[1]["t"], "component": "overall", "from": "ok", "to": "degraded"},
    ]
    assert {"at": rows[3]["t"], "component": "ingest", "from": "ok", "to": "disabled"} in h["incidents"]


def test_history_empty():
    h = health.history([], 7, WED_11_ET)
    assert h["samples"] == 0 and h["uptime_pct"] is None and h["incidents"] == [] and len(h["daily"]) == 7


# --- API ---------------------------------------------------------------------------------------


def test_details_endpoint_from_app_state(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(main.state, "last_edgar_poll", now)
    monkeypatch.setattr(main.state, "last_halts_poll", now)
    monkeypatch.setattr(main.state, "journal_marked", date(2026, 10, 14))
    body = client.get("/api/health/details").json()
    assert body["status"] in ("ok", "degraded")  # no IngestRun rows in the test DB -> ingest degraded
    assert body["components"]["db"]["status"] == "ok"
    assert body["components"]["ingest"]["status"] == "degraded"
    assert body["components"]["journal"]["last_mark"] == "2026-10-14"
    assert body["components"]["edgar_poller"]["status"] == "ok"
    assert "critical" in body["thresholds"]


def test_details_reports_down_when_db_fails(monkeypatch):
    class Broken:
        def __enter__(self):
            raise RuntimeError("db gone")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(main, "SessionLocal", lambda: Broken())
    body = client.get("/api/health/details").json()
    assert body["status"] == "down" and body["components"]["db"]["detail"] == "RuntimeError"
    assert client.get("/api/health").json() == {"ok": True}  # liveness never touches the DB


def test_history_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    now = datetime.now(timezone.utc)
    write_lines(tmp_path, [snap(now - timedelta(hours=2)), snap(now - timedelta(hours=1), "degraded", ingest="degraded")])
    body = client.get("/api/health/history?days=7").json()
    assert body["samples"] == 2 and body["uptime_pct"] == 50.0
    assert body["incidents"][0]["from"] == "ok" and "from_" not in body["incidents"][0] and "from" in body
    assert client.get("/api/health/history?days=0").status_code == 422
    assert client.get("/api/health/history?days=31").status_code == 422


def test_uptime_cycle_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    main.uptime_cycle()
    main.uptime_cycle()
    rows = health.read_snapshots(str(tmp_path))
    assert len(rows) == 2 and set(rows[0]["c"]) >= {"db", "ingest", "edgar_poller"}
