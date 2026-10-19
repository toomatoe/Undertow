"""Deep health check and uptime history (pure functions; main.py gathers the inputs).

Component statuses: ok | degraded | down | disabled | unknown. The overall status is
- down      when the database check fails;
- degraded  when a CRITICAL component (ingest, edgar_poller) is degraded;
- ok        otherwise. The other components are informational and never change the overall status.

Thresholds (documented in the response under `thresholds` too):
- ingest: degraded when the last successful IngestRun is older than INGEST_STALE_FACTOR x INGEST_INTERVAL_SECONDS
  (or there is none yet).
- edgar_poller: degraded when the last fast poll is older than EDGAR_STALE_SECONDS on a weekday between
  06:00 and 22:00 ET (EDGAR accepts filings 06:00-22:00 ET); outside those hours a stale poller is still ok.
  `disabled` when EDGAR_POLL_SECONDS=0 (EDGAR then joins the slow ingest cycle).
- halts_poller: same rule as edgar_poller, informational.

Uptime history: every slow cycle appends one compact line {t, s, c} to {data_dir}/uptime.jsonl. Lines older than
UPTIME_KEEP_DAYS are dropped (the file is rewritten once the oldest line is a day past the limit).
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
EDGAR_STALE_SECONDS = 300
INGEST_STALE_FACTOR = 3
MARKET_OPEN_HOUR_ET, MARKET_CLOSE_HOUR_ET = 6, 22  # EDGAR filing acceptance window
UPTIME_FILE = "uptime.jsonl"
UPTIME_KEEP_DAYS = 30
CRITICAL = ("db", "ingest", "edgar_poller")
UP_STATES = {"ok", "disabled"}
MAX_INCIDENTS = 50


@dataclass
class HealthInputs:
    """Everything evaluate() needs; main.py fills it from the DB and AppState."""

    db_ok: bool
    db_error: str | None = None
    last_ingest_ok: datetime | None = None  # started_at of the newest IngestRun without an error
    last_edgar_poll: datetime | None = None
    last_halts_poll: datetime | None = None
    edgar_poll_seconds: int = 30
    ingest_interval_seconds: int = 300
    journal_marked: date | None = None
    newsletter_latest: dict | None = None  # {id, week_end}
    alerts_channel: str = "none"
    alerts_last: dict | None = None  # {status, reason, at}
    email_enabled: bool = False
    research_active: str | None = None  # active job kind


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def in_edgar_hours(now: datetime) -> bool:
    """Weekday 06:00-22:00 US Eastern."""
    et = _aware(now).astimezone(ET)
    return et.weekday() < 5 and MARKET_OPEN_HOUR_ET <= et.hour < MARKET_CLOSE_HOUR_ET


def _age(now: datetime, then: datetime | None) -> float | None:
    then = _aware(then)
    return None if then is None else round(max((now - then).total_seconds(), 0.0), 1)


def _poller(now: datetime, last: datetime | None, enabled: bool) -> dict:
    if not enabled:
        return {"status": "disabled", "age_seconds": None, "detail": "fast poll off (EDGAR_POLL_SECONDS=0); EDGAR runs in the ingest cycle"}
    age = _age(now, last)
    hours = in_edgar_hours(now)
    stale = age is None or age > EDGAR_STALE_SECONDS
    if stale and hours:
        detail = "no successful poll yet" if age is None else f"last successful poll {int(age)}s ago (limit {EDGAR_STALE_SECONDS}s)"
        return {"status": "degraded", "age_seconds": age, "detail": detail}
    detail = "outside EDGAR hours (weekdays 06:00-22:00 ET)" if stale else "polling"
    return {"status": "ok", "age_seconds": age, "detail": detail}


def evaluate(inp: HealthInputs, now: datetime | None = None) -> dict:
    now = _aware(now) or datetime.now(timezone.utc)
    comps: dict[str, dict] = {}
    comps["db"] = {"status": "ok" if inp.db_ok else "down", "detail": "reachable" if inp.db_ok else (inp.db_error or "query failed")}

    limit = INGEST_STALE_FACTOR * inp.ingest_interval_seconds
    age = _age(now, inp.last_ingest_ok)
    if not inp.db_ok:
        comps["ingest"] = {"status": "unknown", "age_seconds": None, "detail": "database unavailable"}
    elif age is None:
        comps["ingest"] = {"status": "degraded", "age_seconds": None, "detail": "no successful ingest run yet"}
    else:
        ok = age <= limit
        comps["ingest"] = {"status": "ok" if ok else "degraded", "age_seconds": age,
                           "detail": f"last successful run {int(age)}s ago (limit {limit}s)"}

    polling = inp.edgar_poll_seconds > 0
    comps["edgar_poller"] = _poller(now, inp.last_edgar_poll, polling)
    comps["halts_poller"] = _poller(now, inp.last_halts_poll, polling)

    comps["journal"] = ({"status": "ok", "last_mark": inp.journal_marked.isoformat(), "detail": f"prices marked {inp.journal_marked.isoformat()}"}
                        if inp.journal_marked else {"status": "unknown", "last_mark": None, "detail": "not marked since the API started"})
    nl = inp.newsletter_latest
    comps["newsletter"] = ({"status": "ok", "latest_issue": nl.get("id"), "week_end": nl.get("week_end"), "detail": f"latest issue {nl.get('id')}"}
                           if nl else {"status": "unknown", "latest_issue": None, "week_end": None, "detail": "no archived issue yet"})
    alerts_on = inp.alerts_channel not in ("", "none")
    last = inp.alerts_last
    a_status = "disabled" if not alerts_on else ("degraded" if last and last.get("status") == "failed" else "ok")
    comps["alerts"] = {"status": a_status, "enabled": alerts_on, "channel": inp.alerts_channel, "last": last,
                       "detail": "no webhook configured" if not alerts_on else (f"last alert {last.get('status')}" if last else "no alerts sent yet")}
    comps["email"] = {"status": "ok" if inp.email_enabled else "disabled", "enabled": inp.email_enabled,
                      "detail": "SMTP configured" if inp.email_enabled else "SMTP not configured"}
    comps["research_job"] = {"status": "ok", "active": inp.research_active,
                             "detail": f"{inp.research_active} running" if inp.research_active else "idle"}

    if comps["db"]["status"] == "down":
        overall = "down"
    elif any(comps[c]["status"] in ("degraded", "down") for c in CRITICAL):
        overall = "degraded"
    else:
        overall = "ok"
    return {
        "status": overall,
        "checked_at": now.isoformat(),
        "components": comps,
        "thresholds": {
            "ingest_stale_seconds": limit,
            "edgar_stale_seconds": EDGAR_STALE_SECONDS,
            "edgar_hours_et": f"weekdays {MARKET_OPEN_HOUR_ET:02d}:00-{MARKET_CLOSE_HOUR_ET:02d}:00",
            "critical": list(CRITICAL),
        },
    }


# --- Uptime history --------------------------------------------------------------------------


def uptime_path(data_dir: str) -> str:
    return os.path.join(data_dir, UPTIME_FILE)


def snapshot_line(details: dict) -> dict:
    """Compact record of one evaluate() result."""
    return {"t": details["checked_at"], "s": details["status"],
            "c": {k: v["status"] for k, v in details["components"].items()}}


def read_snapshots(data_dir: str) -> list[dict]:
    path = uptime_path(data_dir)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
                datetime.fromisoformat(rec["t"])
                if isinstance(rec.get("c"), dict) and isinstance(rec.get("s"), str):
                    out.append(rec)
            except (ValueError, KeyError, TypeError):
                continue  # torn or foreign line: skip
    return out


def _parse(t: str) -> datetime:
    return _aware(datetime.fromisoformat(t))


def append_snapshot(data_dir: str, details: dict, now: datetime | None = None, keep_days: int = UPTIME_KEEP_DAYS) -> None:
    """Append one line; when the oldest line is more than keep_days + 1 old, rewrite keeping the last keep_days."""
    now = _aware(now) or datetime.now(timezone.utc)
    os.makedirs(data_dir, exist_ok=True)
    path = uptime_path(data_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot_line(details), separators=(",", ":")) + "\n")
    rows = read_snapshots(data_dir)
    if rows and _parse(rows[0]["t"]) < now - timedelta(days=keep_days + 1):
        cutoff = now - timedelta(days=keep_days)
        kept = [r for r in rows if _parse(r["t"]) >= cutoff]
        fd, tmp = tempfile.mkstemp(dir=data_dir, prefix=UPTIME_FILE + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for r in kept:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _pct(up: int, n: int) -> float | None:
    return round(100.0 * up / n, 2) if n else None


def history(snapshots: list[dict], days: int, now: datetime | None = None) -> dict:
    """Uptime % per component and overall, per-UTC-day overall uptime, and status transitions (incidents).

    A sample counts as up when its status is ok or disabled; `unknown` samples are left out of a component's
    denominator. Incidents are status changes between consecutive samples, newest first (max MAX_INCIDENTS).
    """
    now = _aware(now) or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    rows = sorted((r for r in snapshots if start <= _parse(r["t"]) <= now), key=lambda r: r["t"])
    comp_counts: dict[str, list[int]] = {}
    daily: dict[str, list[int]] = {}
    for d in range(days - 1, -1, -1):
        daily[(now - timedelta(days=d)).date().isoformat()] = [0, 0]
    overall_up = 0
    incidents = []
    prev = None
    for r in rows:
        up = r["s"] in UP_STATES
        overall_up += up
        day = _parse(r["t"]).date().isoformat()
        if day in daily:
            daily[day][0] += up
            daily[day][1] += 1
        for name, st in r["c"].items():
            if st == "unknown":
                continue
            c = comp_counts.setdefault(name, [0, 0])
            c[0] += st in UP_STATES
            c[1] += 1
        if prev is not None:
            if prev["s"] != r["s"]:
                incidents.append({"at": r["t"], "component": "overall", "from": prev["s"], "to": r["s"]})
            for name, st in r["c"].items():
                before = prev["c"].get(name)
                if before is not None and before != st:
                    incidents.append({"at": r["t"], "component": name, "from": before, "to": st})
        prev = r
    return {
        "days": days,
        "from": start.isoformat(),
        "to": now.isoformat(),
        "samples": len(rows),
        "uptime_pct": _pct(overall_up, len(rows)),
        "components": {k: {"uptime_pct": _pct(u, n), "samples": n} for k, (u, n) in sorted(comp_counts.items())},
        "daily": [{"day": k, "uptime_pct": _pct(u, n), "samples": n} for k, (u, n) in daily.items()],
        "incidents": incidents[::-1][:MAX_INCIDENTS],
    }
