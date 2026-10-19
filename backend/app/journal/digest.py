"""Tamper-evident track record: a daily SHA-256 hash chain over journal entries.

Each completed UTC day's journal entries (record-time fields only) are serialized canonically and
hashed together with the previous day's hash. The chain lives in `{data_dir}/journal_chain.jsonl`,
one line per sealed day, append-only. Publishing the head hash somewhere dated and immutable (the
weekly newsletter) means a later silent edit or deletion of a sealed entry is detectable by anyone.

Canonical form of one day (a third party can recompute it from `export_day()` with plain Python):

    payload = {"day": "YYYY-MM-DD", "prev": <prev_hash>, "entries": [<entry>, ...]}   # entries sorted by id
    hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

Each entry holds the RECORD_FIELDS below. Datetimes are UTC, formatted `YYYY-MM-DDTHH:MM:SS.ffffffZ`;
floats are rounded to FLOAT_DIGITS decimals (`round(x, 8)`); lists keep their order (signals are
most severe first). Marking fields (status, entry_date/price, abn_*, marked_at) are filled in later
by a deterministic computation from prices and are deliberately NOT sealed.

Public API (wired into routes and the scheduler elsewhere):
    seal_through(session, data_dir, through_day, now=None) -> list[dict]   new chain lines
    verify_chain(session, data_dir) -> dict
    export_day(session, data_dir, day) -> dict | None
    chain_head(data_dir) -> dict | None

CLI:
    python -m app.journal.digest seal [--through YYYY-MM-DD]   # default: yesterday (UTC)
    python -m app.journal.digest verify                         # exit code 1 when the chain does not verify
    python -m app.journal.digest export YYYY-MM-DD
"""

import argparse
import hashlib
import json
import os
import sys
import threading
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.journal import service as journal
from app.models import JournalEntry

CHAIN_FILE = "journal_chain.jsonl"
GENESIS = "0" * 64
FLOAT_DIGITS = 8
LATE_AFTER_DAYS = 2  # sealed_late when the seal's UTC date is more than 2 days after the sealed day
RECORD_FIELDS = (
    "id", "article_id", "ticker", "cik", "form", "signals", "primary_signal", "direction", "severity",
    "size_bucket", "public_float", "filed_at", "created_at", "borrow_fee", "borrow_available", "borrow_snapshot",
)
_LOCK = threading.Lock()  # one writer per process (scheduler + API share it)


class ChainError(RuntimeError):
    """The chain file is unreadable or malformed; nothing is appended to it."""


# --- canonical form ------------------------------------------------------------------


def _ts(dt: datetime) -> str:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canon(v):
    if isinstance(v, datetime):
        return _ts(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return round(v, FLOAT_DIGITS)
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in v.items()}
    return v


def canonical_entry(e: JournalEntry) -> dict:
    return {f: _canon(getattr(e, f)) for f in RECORD_FIELDS}


def canonical_entries(session: Session, day: date) -> list[dict]:
    """Record-time fields of the entries recorded (created_at) on UTC `day`, sorted by id."""
    return [canonical_entry(e) for e in journal.entries_recorded_on(session, day)]


def day_hash(entries: list[dict], prev_hash: str, day: date | str) -> str:
    """sha256 hex of the canonical JSON of {day, prev, entries}."""
    payload = {"day": day if isinstance(day, str) else day.isoformat(), "prev": prev_hash, "entries": _canon(entries)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


# --- chain file ----------------------------------------------------------------------


def chain_path(data_dir: str) -> str:
    return os.path.join(data_dir, CHAIN_FILE)


def _read(data_dir: str) -> tuple[list[dict], str | None]:
    """(records, error). Error describes the first unparseable line or a torn final write."""
    path = chain_path(data_dir)
    if not os.path.exists(path):
        return [], None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text and not text.endswith("\n"):
        return [], "last line is incomplete (torn write)"
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            return out, f"line {n} is blank"
        try:
            rec = json.loads(line)
            date.fromisoformat(rec["day"])
            if not all(isinstance(rec.get(k), str) and len(rec[k]) == 64 for k in ("prev_hash", "hash")):
                raise ValueError("bad hash")
        except (ValueError, KeyError, TypeError):
            return out, f"line {n} is malformed"
        out.append(rec)
    return out, None


def _append(data_dir: str, rec: dict) -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(chain_path(data_dir), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def is_late(day: date, sealed_at: datetime) -> bool:
    return (sealed_at.astimezone(timezone.utc).date() - day).days > LATE_AFTER_DAYS


# --- public API ------------------------------------------------------------------------


def seal_through(session: Session, data_dir: str, through_day: date, now: datetime | None = None) -> list[dict]:
    """Seal every unsealed UTC day from the first journal day up to `through_day` inclusive.

    Never seals today or a future day (`through_day` is capped at yesterday, UTC). Idempotent: days
    already in the chain are skipped, so a rerun appends nothing. Days with no entries are sealed
    too (count 0), keeping the chain contiguous. Returns the lines appended.
    """
    now = now or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    last_allowed = now.astimezone(timezone.utc).date() - timedelta(days=1)
    through_day = min(through_day, last_allowed)
    with _LOCK:
        records, err = _read(data_dir)
        if err:
            raise ChainError(f"{chain_path(data_dir)}: {err}; refusing to append")
        if records:
            day = date.fromisoformat(records[-1]["day"]) + timedelta(days=1)
            prev = records[-1]["hash"]
        else:
            day = journal.first_recorded_day(session)
            prev = GENESIS
            if day is None:
                return []
        added = []
        while day <= through_day:
            entries = canonical_entries(session, day)
            rec = {
                "day": day.isoformat(),
                "prev_hash": prev,
                "hash": day_hash(entries, prev, day),
                "count": len(entries),
                "sealed_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sealed_late": is_late(day, now),
            }
            _append(data_dir, rec)
            added.append(rec)
            prev = rec["hash"]
            day += timedelta(days=1)
        return added


def verify_chain(session: Session, data_dir: str) -> dict:
    """Recompute every sealed day from the DB and check the links in the file.

    Returns {ok, days, head_hash, head_day, first_mismatch, broken_link, late_days}:
    - first_mismatch {day, expected, actual}: first day whose stored hash (expected) differs from the
      hash recomputed from today's DB rows with the stored prev_hash (actual).
    - broken_link {day, expected_prev, actual_prev, reason}: first place the file itself is broken
      (a removed or reordered line, a gap between days, a malformed line, or journal entries that
      predate the first sealed day).
    """
    records, err = _read(data_dir)
    first_mismatch = broken = None
    prev, prev_day = GENESIS, None
    for rec in records:
        day = date.fromisoformat(rec["day"])
        if broken is None:
            if rec["prev_hash"] != prev:
                broken = {"day": rec["day"], "expected_prev": prev, "actual_prev": rec["prev_hash"], "reason": "prev_hash does not match the previous line"}
            elif prev_day is not None and day != prev_day + timedelta(days=1):
                broken = {"day": rec["day"], "expected_prev": prev, "actual_prev": rec["prev_hash"], "reason": f"gap or reorder after {prev_day.isoformat()}"}
        if first_mismatch is None:
            actual = day_hash(canonical_entries(session, day), rec["prev_hash"], day)
            if actual != rec["hash"]:
                first_mismatch = {"day": rec["day"], "expected": rec["hash"], "actual": actual}
        prev, prev_day = rec["hash"], day
    if err and broken is None:
        broken = {"day": None, "expected_prev": prev, "actual_prev": None, "reason": err}
    if records and broken is None:
        first = journal.first_recorded_day(session)
        if first is not None and first < date.fromisoformat(records[0]["day"]):
            broken = {"day": first.isoformat(), "expected_prev": None, "actual_prev": None, "reason": "entries recorded before the first sealed day"}
    return {
        "ok": first_mismatch is None and broken is None,
        "days": len(records),
        "head_hash": records[-1]["hash"] if records else None,
        "head_day": records[-1]["day"] if records else None,
        "first_mismatch": first_mismatch,
        "broken_link": broken,
        "late_days": [r["day"] for r in records if r.get("sealed_late")],
    }


def export_day(session: Session, data_dir: str, day: date) -> dict | None:
    """{day, prev_hash, hash, entries} for a sealed day (None if not sealed), enough to recompute the hash."""
    records, _ = _read(data_dir)
    rec = next((r for r in records if r["day"] == day.isoformat()), None)
    if rec is None:
        return None
    return {"day": rec["day"], "prev_hash": rec["prev_hash"], "hash": rec["hash"], "entries": canonical_entries(session, day)}


def chain_head(data_dir: str) -> dict | None:
    """{head_hash, head_day, days} of the chain file, or None when nothing is sealed (or the file is unreadable)."""
    records, err = _read(data_dir)
    if not records or err:
        return None
    return {"head_hash": records[-1]["hash"], "head_day": records[-1]["day"], "days": len(records)}


# --- CLI -------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings
    from app.db import SessionLocal, init_db

    p = argparse.ArgumentParser(description="Track-record hash chain over journal entries")
    sub = p.add_subparsers(dest="cmd", required=True)
    s_seal = sub.add_parser("seal", help="Seal completed UTC days (never today)")
    s_seal.add_argument("--through", type=date.fromisoformat, help="Last day to seal. Default: yesterday (UTC)")
    sub.add_parser("verify", help="Recompute the chain from the DB")
    s_exp = sub.add_parser("export", help="Print one sealed day's entries and hashes")
    s_exp.add_argument("day", type=date.fromisoformat)
    args = p.parse_args(argv)

    s = get_settings()
    init_db()
    with SessionLocal() as session:
        if args.cmd == "seal":
            through = args.through or (datetime.now(timezone.utc).date() - timedelta(days=1))
            added = seal_through(session, s.data_dir, through)
            for r in added:
                print(f"sealed {r['day']}: {r['hash']} ({r['count']} entries{', late' if r['sealed_late'] else ''})")
            print(json.dumps({"added": len(added), "head": chain_head(s.data_dir)}, indent=2))
            return 0
        if args.cmd == "verify":
            res = verify_chain(session, s.data_dir)
            print(json.dumps(res, indent=2))
            return 0 if res["ok"] else 1
        out = export_day(session, s.data_dir, args.day)
        if out is None:
            print(f"{args.day.isoformat()} is not sealed", file=sys.stderr)
            return 1
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0


if __name__ == "__main__":
    sys.exit(main())
