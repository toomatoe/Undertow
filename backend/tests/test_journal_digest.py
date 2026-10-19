import hashlib
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from app.db import Base, SessionLocal, engine
from app.journal import digest
from app.journal.service import entries_recorded_on
from app.models import JournalEntry

D1, D2, D3 = date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)
NOW = datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)  # D3 is yesterday


def utc(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def add(s, n: int, created: datetime, ticker="TINY", borrow_fee=0.123456789123):
    e = JournalEntry(article_id=n, ticker=ticker, cik=n, form="8-K", signals=["delisting_notice", "officer_change"],
                     primary_signal="delisting_notice", direction="-", severity=3, size_bucket="nano", public_float=20_000_000,
                     filed_at=created - timedelta(hours=1), created_at=created, borrow_fee=borrow_fee, borrow_available=-1,
                     borrow_snapshot="20261013_0900", status="waiting")
    s.add(e)
    return e


def lines(data_dir) -> list[dict]:
    return [json.loads(x) for x in (data_dir / digest.CHAIN_FILE).read_text().splitlines()]


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        add(s, 1, utc(D1, 14))
        add(s, 2, utc(D1, 23, 59), ticker="MICR")
        add(s, 3, utc(D2, 0, 1))  # just after midnight UTC: belongs to D2
        add(s, 4, utc(D3, 12))
        add(s, 5, utc(D3 + timedelta(days=1), 1))  # "today" relative to NOW
        s.commit()


def test_entries_grouped_by_utc_recorded_day():
    with SessionLocal() as s:
        assert [e.article_id for e in entries_recorded_on(s, D1)] == [1, 2]
        assert [e.article_id for e in entries_recorded_on(s, D2)] == [3]


def test_seal_two_days_links_and_is_idempotent(tmp_path):
    with SessionLocal() as s:
        added = digest.seal_through(s, str(tmp_path), D2, now=NOW)
        assert [r["day"] for r in added] == ["2026-10-13", "2026-10-14"]
        chain = lines(tmp_path)
        assert chain[0]["prev_hash"] == digest.GENESIS and chain[1]["prev_hash"] == chain[0]["hash"]
        assert [r["count"] for r in chain] == [2, 1]
        assert chain[0]["hash"] == digest.day_hash(digest.canonical_entries(s, D1), digest.GENESIS, D1)
        before = (tmp_path / digest.CHAIN_FILE).read_bytes()
        assert digest.seal_through(s, str(tmp_path), D2, now=NOW) == []  # re-seal is a no-op
        assert (tmp_path / digest.CHAIN_FILE).read_bytes() == before
        assert digest.chain_head(str(tmp_path)) == {"head_hash": chain[1]["hash"], "head_day": "2026-10-14", "days": 2}
        res = digest.verify_chain(s, str(tmp_path))
        assert res["ok"] and res["days"] == 2 and res["first_mismatch"] is None and res["broken_link"] is None
        # Later seals append to the same file without rewriting earlier lines
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
        assert (tmp_path / digest.CHAIN_FILE).read_bytes().startswith(before)
        assert lines(tmp_path)[2]["prev_hash"] == chain[1]["hash"]


def test_today_and_future_never_sealed(tmp_path):
    with SessionLocal() as s:
        added = digest.seal_through(s, str(tmp_path), D3 + timedelta(days=5), now=NOW)
        assert [r["day"] for r in added] == ["2026-10-13", "2026-10-14", "2026-10-15"]  # stops at yesterday
        assert digest.seal_through(s, str(tmp_path), D3 + timedelta(days=1), now=NOW) == []
    assert digest.chain_head(str(tmp_path))["head_day"] == "2026-10-15"


def test_empty_journal_and_no_chain(tmp_path):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        assert digest.seal_through(s, str(tmp_path), D3, now=NOW) == []
        assert digest.chain_head(str(tmp_path)) is None
        res = digest.verify_chain(s, str(tmp_path))
        assert res["ok"] and res["days"] == 0 and res["head_hash"] is None


def test_empty_days_are_sealed_with_zero_count(tmp_path):
    with SessionLocal() as s:
        s.query(JournalEntry).filter(JournalEntry.article_id == 3).delete()
        s.commit()
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
    assert [r["count"] for r in lines(tmp_path)] == [2, 0, 1]


def test_sealed_late_flag(tmp_path):
    with SessionLocal() as s:
        # Backfill on Oct 16: Oct 13 is 3 days back (late), Oct 14 is 2 days back (not late)
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
    chain = lines(tmp_path)
    assert [r["sealed_late"] for r in chain] == [True, False, False]
    assert chain[0]["sealed_at"] == "2026-10-16T02:00:00Z"
    assert digest.is_late(D1, utc(D1 + timedelta(days=2), 23, 59)) is False
    assert digest.is_late(D1, utc(D1 + timedelta(days=3), 0, 0)) is True
    with SessionLocal() as s:
        assert digest.verify_chain(s, str(tmp_path))["late_days"] == ["2026-10-13"]


@pytest.mark.parametrize("field,value", [
    ("ticker", "EVIL"), ("signals", ["officer_change"]), ("size_bucket", "micro"), ("borrow_fee", 0.5),
    ("filed_at", utc(D1, 9)), ("created_at", utc(D2, 3)),
])
def test_tampering_record_field_is_detected(tmp_path, field, value):
    with SessionLocal() as s:
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
        e = s.query(JournalEntry).filter(JournalEntry.article_id == 2).one()
        setattr(e, field, value)
        s.commit()
        res = digest.verify_chain(s, str(tmp_path))
    assert not res["ok"]
    assert res["first_mismatch"]["day"] == "2026-10-13"
    assert res["first_mismatch"]["expected"] == lines(tmp_path)[0]["hash"] != res["first_mismatch"]["actual"]
    assert res["broken_link"] is None


def test_deleting_an_entry_is_detected(tmp_path):
    with SessionLocal() as s:
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
        s.query(JournalEntry).filter(JournalEntry.article_id == 3).delete()
        s.commit()
        assert digest.verify_chain(s, str(tmp_path))["first_mismatch"]["day"] == "2026-10-14"


def test_mark_updates_do_not_break_chain(tmp_path):
    with SessionLocal() as s:
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
        for e in s.query(JournalEntry).all():
            e.status, e.entry_date, e.entry_price, e.raw_entry_price = "complete", D3, 1.23, 1.25
            e.abn_1, e.abn_5, e.abn_20, e.marked_at = 0.01, -0.02, -0.1, NOW
        s.commit()
        assert digest.verify_chain(s, str(tmp_path))["ok"]


def test_deleting_a_chain_line_breaks_the_link(tmp_path):
    with SessionLocal() as s:
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
        path = tmp_path / digest.CHAIN_FILE
        kept = path.read_text().splitlines()
        path.write_text("\n".join([kept[0], kept[2]]) + "\n")
        res = digest.verify_chain(s, str(tmp_path))
        assert not res["ok"] and res["broken_link"]["day"] == "2026-10-15"
        assert res["broken_link"]["expected_prev"] == json.loads(kept[0])["hash"]

        path.write_text("\n".join(kept[1:]) + "\n")  # first line removed
        res = digest.verify_chain(s, str(tmp_path))
        assert not res["ok"] and res["broken_link"]["day"] == "2026-10-14" and res["broken_link"]["expected_prev"] == digest.GENESIS


def test_corrupt_file_refuses_to_append(tmp_path):
    with SessionLocal() as s:
        digest.seal_through(s, str(tmp_path), D2, now=NOW)
        path = tmp_path / digest.CHAIN_FILE
        path.write_text(path.read_text() + '{"day": "2026-10-15", "prev')  # torn write
        with pytest.raises(digest.ChainError):
            digest.seal_through(s, str(tmp_path), D3, now=NOW)
        assert digest.chain_head(str(tmp_path)) is None
        assert digest.verify_chain(s, str(tmp_path))["broken_link"]["reason"].startswith("last line is incomplete")


def test_export_day_recomputes_with_plain_hashlib(tmp_path):
    with SessionLocal() as s:
        digest.seal_through(s, str(tmp_path), D3, now=NOW)
        exp = digest.export_day(s, str(tmp_path), D1)
        assert digest.export_day(s, str(tmp_path), D3 + timedelta(days=1)) is None  # not sealed
    # A third party with only the exported JSON and the standard library:
    exported = json.loads(json.dumps(exp))
    payload = {"day": exported["day"], "prev": exported["prev_hash"], "entries": exported["entries"]}
    recomputed = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    assert recomputed == exported["hash"] == lines(tmp_path)[0]["hash"]
    assert exported["prev_hash"] == digest.GENESIS
    first = exported["entries"][0]
    assert set(first) == set(digest.RECORD_FIELDS)
    assert first["created_at"] == "2026-10-13T14:00:00.000000Z" and first["filed_at"] == "2026-10-13T13:00:00.000000Z"
    assert first["borrow_fee"] == 0.12345679  # rounded to 8 decimals
    assert "status" not in first and "abn_20" not in first and "entry_price" not in first


def test_naive_and_aware_datetimes_canonicalize_the_same():
    aware = datetime(2026, 10, 13, 10, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert digest._canon(aware) == digest._canon(datetime(2026, 10, 13, 14, 0)) == "2026-10-13T14:00:00.000000Z"


# --- writer lock (scheduler seal_cycle vs CLI seal) -----------------------------------------


def _lock_is_free(data_dir) -> bool:
    """True when no one holds the chain lock (fcntl: a non-blocking flock succeeds; fallback: no lock file)."""
    if digest.fcntl is None:
        return not os.path.exists(digest.chain_path(str(data_dir)) + digest.EXCL_LOCK_SUFFIX)
    fd = os.open(digest.chain_path(str(data_dir)) + digest.LOCK_SUFFIX, os.O_RDWR | os.O_CREAT)
    try:
        digest.fcntl.flock(fd, digest.fcntl.LOCK_EX | digest.fcntl.LOCK_NB)
        digest.fcntl.flock(fd, digest.fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def test_sequential_seals_are_idempotent_and_release_the_lock(tmp_path):
    with SessionLocal() as s:
        assert [r["day"] for r in digest.seal_through(s, str(tmp_path), D3, now=NOW)] == ["2026-10-13", "2026-10-14", "2026-10-15"]
        assert _lock_is_free(tmp_path)
        assert digest.seal_through(s, str(tmp_path), D3, now=NOW) == []
        assert _lock_is_free(tmp_path)
    assert [r["day"] for r in lines(tmp_path)] == ["2026-10-13", "2026-10-14", "2026-10-15"]


def test_fallback_lock_without_fcntl(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "fcntl", None)
    lock = tmp_path / (digest.CHAIN_FILE + digest.EXCL_LOCK_SUFFIX)
    lock.write_text("12345")  # left behind by a crashed writer
    old = time.time() - digest.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))
    with SessionLocal() as s:
        assert len(digest.seal_through(s, str(tmp_path), D2, now=NOW)) == 2  # stale lock removed
        assert not lock.exists()  # released
        assert digest.seal_through(s, str(tmp_path), D2, now=NOW) == []
        assert not lock.exists()
        lock.write_text("999")  # a live writer holds it: give up rather than append unlocked
        monkeypatch.setattr(digest, "LOCK_TIMEOUT_SECONDS", 0.2)
        with pytest.raises(digest.ChainError):
            digest.seal_through(s, str(tmp_path), D3, now=NOW)
    assert [r["day"] for r in lines(tmp_path)] == ["2026-10-13", "2026-10-14"]


def test_seal_waiting_on_another_writer_rechecks_under_the_lock(tmp_path):
    """Another process (simulated: a second flock/lock file outside the module's thread lock) seals D1..D2 while a
    scheduler seal is waiting; the waiting seal must then append only D3, never D1/D2 a second time."""
    data_dir = str(tmp_path)
    with SessionLocal() as s:  # the other writer's lines, computed before any thread touches the DB
        h1 = digest.day_hash(digest.canonical_entries(s, D1), digest.GENESIS, D1)
        h2 = digest.day_hash(digest.canonical_entries(s, D2), h1, D2)
    other = [
        {"day": D1.isoformat(), "prev_hash": digest.GENESIS, "hash": h1, "count": 2, "sealed_at": "2026-10-16T01:00:00Z", "sealed_late": False},
        {"day": D2.isoformat(), "prev_hash": h1, "hash": h2, "count": 1, "sealed_at": "2026-10-16T01:00:00Z", "sealed_late": False},
    ]
    if digest.fcntl is not None:
        fd = os.open(digest.chain_path(data_dir) + digest.LOCK_SUFFIX, os.O_RDWR | os.O_CREAT)
        digest.fcntl.flock(fd, digest.fcntl.LOCK_EX)
        release = lambda: (digest.fcntl.flock(fd, digest.fcntl.LOCK_UN), os.close(fd))  # noqa: E731
    else:
        lock = tmp_path / (digest.CHAIN_FILE + digest.EXCL_LOCK_SUFFIX)
        lock.write_text("other")
        release = lock.unlink

    result: dict = {}

    def scheduler_seal():
        with SessionLocal() as s:
            result["added"] = digest.seal_through(s, data_dir, D3, now=NOW)

    t = threading.Thread(target=scheduler_seal)
    t.start()
    try:
        t.join(0.3)
        assert t.is_alive() and not (tmp_path / digest.CHAIN_FILE).exists()  # blocked on the lock, nothing written
        for rec in other:
            digest._append(data_dir, rec)
    finally:
        release()
    t.join(10)
    assert not t.is_alive()
    assert [r["day"] for r in result["added"]] == ["2026-10-15"]
    assert [r["day"] for r in lines(tmp_path)] == ["2026-10-13", "2026-10-14", "2026-10-15"]
    with SessionLocal() as s:
        assert digest.verify_chain(s, data_dir)["ok"]
    assert _lock_is_free(tmp_path)
