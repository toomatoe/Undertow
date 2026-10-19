import hashlib
import json
import math
import os
import random
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.research.eventstudy as es
from app.pipeline.companies import FloatRecord, bucket_for, parse_frame
from app.pipeline.signals import SignalDef, signals_for_filing
from app.research import snapshot
from app.research.eventstudy import (
    ET,
    Event,
    clustered_t,
    clustered_welch_t,
    day0_index,
    measure,
    summarize,
    t_stat,
)
from app.research.prices import PriceSeries, parse_chart

# Mon 2026-03-02 .. Fri 2026-03-13, weekdays only
DAYS = [date(2026, 3, 2) + timedelta(days=i) for i in range(12) if (date(2026, 3, 2) + timedelta(days=i)).weekday() < 5]


def series(closes):
    return PriceSeries("X", DAYS[: len(closes)], closes)


def test_day0_before_and_after_cutoff():
    s = series([10.0] * 10)
    # Tue 10:00 ET -> same day (index 1); Tue 16:05 ET -> Wed (index 2)
    assert day0_index(s, datetime(2026, 3, 3, 10, 0, tzinfo=ET)) == 1
    assert day0_index(s, datetime(2026, 3, 3, 16, 5, tzinfo=ET)) == 2
    # Fri evening -> Monday
    assert s.dates[day0_index(s, datetime(2026, 3, 6, 18, 0, tzinfo=ET))] == date(2026, 3, 9)
    # Before the first bar: no previous close to measure the reaction from
    assert day0_index(s, datetime(2026, 3, 2, 9, 0, tzinfo=ET)) is None


def test_measure_is_market_adjusted(monkeypatch):
    import app.research.eventstudy as es

    monkeypatch.setattr(es, "HORIZONS", [5])
    stock = series([10, 10, 9, 9, 9, 9, 9, 8.1, 8.1, 8.1])  # -10% reaction, then -10% drift
    bench = series([100] * 10)
    ev = Event(1, "X", "micro", "auditor_change", datetime(2026, 3, 3, 16, 5, tzinfo=ET))
    m = measure(ev, stock, bench)
    assert round(m["reaction"], 4) == -0.1
    assert round(m["drift_5"], 4) == -0.1


def _obs(signal, n, d5, d20):
    return [{"signal": signal, "bucket": "micro", "ticker": f"T{i}", "reaction": -0.05,
             "drift_5": d5 + (i % 5) * 0.004, "drift_20": d20 + (i % 5) * 0.004} for i in range(n)]


def test_summarize_needs_to_beat_baseline():
    events = _obs("auditor_change", 40, -0.08, -0.10)
    ordinary = _obs("baseline", 200, 0.0, 0.0)
    results, testing = summarize(events + ordinary)
    assert testing["n_tests"] == 2  # baseline is not a test
    r20 = next(r for r in results if r["horizon_days"] == 20)
    assert r20["n"] == 40 and r20["borrow"] > 0 and r20["mean_net"] > 0
    assert r20["excess_vs_baseline"] < 0 and r20["significant"]

    # Same drift, but ordinary days drift just as much: the filing adds nothing
    lagging = _obs("baseline", 200, -0.08, -0.10)
    r20 = next(r for r in summarize(events + lagging)[0] if r["horizon_days"] == 20)
    assert abs(r20["excess_vs_baseline"]) < 1e-9 and not r20["significant"]

    # Under MIN_N events: no result at all
    assert summarize(events[:5] + ordinary)[0] == []


def test_signals_for_filing():
    assert [s.code for s in signals_for_filing("8-K", ["4.01", "9.01", "5.02"])] == ["auditor_change", "officer_change"]
    assert [s.code for s in signals_for_filing("424B5", [])] == ["offering_priced"]
    assert signals_for_filing("10-Q", []) == []


def test_buckets_and_frame():
    assert bucket_for(20e6) == "nano"
    assert bucket_for(299e6) == "micro"
    assert bucket_for(5e9) == "mid"
    assert bucket_for(None) is None
    frame = {"data": [{"cik": 1, "val": 1e8, "end": "2023-06-30"}, {"cik": 1, "val": 2e8, "end": "2024-06-30"}]}
    assert parse_frame(frame)[1].public_float == 2e8


def test_parse_chart_skips_missing():
    payload = {"chart": {"result": [{"timestamp": [1772458200, 1772544600], "indicators": {"adjclose": [{"adjclose": [None, 5.0]}]}}]}}
    s = parse_chart("X", payload)
    assert len(s) == 1 and s.close == [5.0]
    assert parse_chart("X", {"chart": {"result": None}}) is None


# --- StudyDesign / run_design / clustered t / offline (2026-10-19) -----------------


def _bdays(a, b):
    out, d = [], a
    while d <= b:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def stub_world(monkeypatch, tmp_path):
    """Synthetic frame, filings and prices; no network. The same stubs produced GOLDEN on the pre-refactor run()."""
    floats = {c: FloatRecord(c, 20e6, "2023-06-30") for c in range(1, 13)}
    floats.update({c: FloatRecord(c, 100e6, "2023-06-30") for c in range(101, 113)})
    monkeypatch.setattr(es, "fetch_frame", lambda *a, **k: floats)
    monkeypatch.setattr(es.time, "sleep", lambda s: None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def events(cik, bucket, ua, cache_dir=None, **kw):
        if cik % 7 == 0:
            return None, [], "no_ticker"
        t = f"T{cik}"
        out = []
        for k in range(8):
            d = date(2024, 1, 3) + timedelta(days=37 * k + cik)
            out.append(Event(cik, t, bucket, "offering_priced", datetime(d.year, d.month, d.day, 9 + k % 9, 0, tzinfo=ET)))
            d2 = d + timedelta(days=11)
            out.append(Event(cik, t, bucket, "material_agreement", datetime(d2.year, d2.month, d2.day, 16, 10, tzinfo=ET)))
        return t, out, "ok"

    def prices(ticker, start, end, cache_dir, *a, **k):
        if ticker.startswith("T") and int(ticker[1:]) % 3 == 0:
            return None
        days = _bdays(start, end)
        rng = random.Random(sum(map(ord, ticker)))
        px, closes = 10.0, []
        for _ in days:
            px *= 1 + rng.gauss(-0.0005 if ticker.startswith("T") else 0.0003, 0.03)
            closes.append(px)
        return PriceSeries(ticker, days, closes)

    monkeypatch.setattr(es, "company_events", events)
    monkeypatch.setattr(es, "load_prices", prices)
    return floats, events


# sha256 of the canonical (sort_keys) JSON of run({"nano": 4, "micro": 4}) minus generated_at, computed with
# the pre-refactor eventstudy.py (commit 4f542c6) on stub_world.
GOLDEN = "73ce5ca543b84105f528c09662409ccd3ab9679c4c55f6bb2d80f9c64557f0ad"
ADDITIVE_ROW_FIELDS = {"t_stat_clustered", "t_vs_baseline_clustered", "clusters"}


def _strip_additive(out):
    out = json.loads(json.dumps(out))
    out.pop("generated_at")
    out["config"].pop("study")
    out["config"].pop("design")
    for r in out["results"]:
        for f in ADDITIVE_ROW_FIELDS:
            r.pop(f)
    assert out["caveats"][-1].startswith("t_stat_clustered")
    out["caveats"].pop()
    return out


def test_run_wrapper_reproduces_pre_refactor_output(monkeypatch, tmp_path):
    stub_world(monkeypatch, tmp_path)
    out = es.run({"nano": 4, "micro": 4})
    assert out["config"]["study"] == "in_sample"
    assert out["config"]["design"]["seed"] == 7 and out["config"]["design"]["float_year"] == 2023
    assert out["config"]["design"]["exclude_ciks"]["count"] == 0
    assert out["results"] and all(ADDITIVE_ROW_FIELDS <= set(r) for r in out["results"])
    assert all(r["clusters"] == r["companies"] for r in out["results"])
    stripped = _strip_additive(out)
    assert hashlib.sha256(json.dumps(stripped, sort_keys=True).encode()).hexdigest() == GOLDEN


def test_run_design_with_stub_event_source_matches_run(monkeypatch, tmp_path):
    _, events = stub_world(monkeypatch, tmp_path)
    calls = []

    def source(cik, bucket, ua, cache_dir, *, window, offline):
        calls.append((window, offline))
        return events(cik, bucket, ua, cache_dir)

    design = es.in_sample_design({"nano": 4, "micro": 4})
    a = es.run_design(design, event_source=source, data_dir=str(tmp_path), user_agent="test")
    b = es.run({"nano": 4, "micro": 4})
    assert calls and all(c == ((es.WINDOW_START, es.WINDOW_END), False) for c in calls)
    a.pop("generated_at"), b.pop("generated_at")
    assert a == b


def test_summarize_accepts_custom_signal_defs():
    defs = {"insider_buy": SignalDef("insider_buy", "Insider buy", "+", 2, "x")}
    events = [dict(m, signal="insider_buy") for m in _obs("x", 40, 0.08, 0.10)]
    results, _ = summarize(events + _obs("baseline", 200, 0.0, 0.0), signal_defs=defs)
    assert {r["label"] for r in results} == {"Insider buy"} and all(r["direction"] == "+" for r in results)


def test_clustered_t_equals_plain_t_with_singleton_clusters():
    rng = random.Random(1)
    x = [rng.gauss(0.01, 0.05) for _ in range(60)]
    # CR1 with G = n: G/(G-1) * sum (x - mean)^2 / n^2 == var / n, so the t-stats agree exactly
    assert math.isclose(clustered_t(x, list(range(60))), t_stat(x), rel_tol=1e-9)


def test_clustered_t_smaller_when_events_duplicated_within_firm():
    rng = random.Random(2)
    base = [rng.gauss(0.02, 0.05) for _ in range(30)]
    dup = [v for v in base for _ in range(4)]  # each firm's event counted 4 times
    firms = [i for i in range(30) for _ in range(4)]
    naive = t_stat(dup)
    clustered = clustered_t(dup, firms)
    assert abs(clustered) < abs(naive)
    assert math.isclose(naive / clustered, 2.0, rel_tol=0.05)  # ~sqrt(4): duplicates add no information
    assert clustered_t(dup, [0] * len(dup)) == 0.0  # fewer than 2 clusters


def test_clustered_welch_t():
    a = [0.05 + 0.01 * (i % 3) for i in range(30)]
    b = [0.0 + 0.01 * (i % 3) for i in range(60)]
    ca, cb = list(range(30)), list(range(60))
    t = clustered_welch_t(a, ca, b, cb)
    se_a = statistics.stdev(a) / math.sqrt(30)
    se_b = statistics.stdev(b) / math.sqrt(60)
    assert math.isclose(t, (statistics.mean(a) - statistics.mean(b)) / math.sqrt(se_a**2 + se_b**2), rel_tol=1e-9)
    assert t > 0
    assert clustered_welch_t(a, [1] * 30, b, cb) == 0.0
    # Duplicated firms on the event side shrink the statistic
    assert abs(clustered_welch_t(a, [i % 3 for i in range(30)], b, cb)) < abs(t)


def test_summarize_significant_unchanged_by_clustering():
    """`significant` ignores the clustered fields: events from only 2 firms, the plain t still decides."""
    events = [dict(m, ticker=f"T{i % 5 // 3}") for i, m in enumerate(_obs("auditor_change", 40, -0.08, -0.10))]
    results, _ = summarize(events + _obs("baseline", 200, 0.0, 0.0))
    r20 = next(r for r in results if r["horizon_days"] == 20)
    assert r20["clusters"] == 2 and r20["significant"]
    assert abs(r20["t_stat_clustered"]) < abs(r20["t_stat"])


def test_sample_universe_excludes_and_is_deterministic(monkeypatch, tmp_path):
    stub_world(monkeypatch, tmp_path)
    sizes = {"nano": 2, "micro": 2}
    a = es.sample_universe(sizes, str(tmp_path), "ua", seed=11)
    assert a == es.sample_universe(sizes, str(tmp_path), "ua", seed=11)
    assert {len(v) for v in a.values()} == {5}  # 2.5x oversample
    excluded = frozenset(a["nano"] + a["micro"])
    b = es.sample_universe(sizes, str(tmp_path), "ua", seed=11, exclude_ciks=excluded, float_year=2020)
    assert not excluded & set(b["nano"] + b["micro"])
    assert b == es.sample_universe(sizes, str(tmp_path), "ua", seed=11, exclude_ciks=excluded, float_year=2020)
    assert es.sample_universe(sizes, str(tmp_path), "ua", seed=12) != a


@pytest.fixture
def no_network(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("network access in offline mode")

    for name in ("get", "post", "request", "stream", "Client", "AsyncClient"):
        monkeypatch.setattr(httpx, name, boom)
    snapshot.start_tracking()
    yield
    snapshot.stop_tracking()


def test_offline_get_json_and_load_prices_never_fetch(no_network, tmp_path):
    from app.research.prices import load_prices

    cached = tmp_path / "sub" / "1.json"
    cached.parent.mkdir()
    cached.write_text(json.dumps({"ok": 1}))
    assert es.get_json("https://example.invalid/1", "ua", str(cached), offline=True) == {"ok": 1}
    assert es.get_json("https://example.invalid/2", "ua", str(tmp_path / "sub" / "2.json"), offline=True) is None
    assert load_prices("ZZZ", date(2024, 1, 1), date(2024, 2, 1), str(tmp_path / "prices"), offline=True) is None
    misses = snapshot.misses()
    assert len(misses) == 2 and misses[0].endswith("2.json") and "ZZZ_2024-01-01_2024-02-01.json" in misses[1]
    assert cached.resolve() in {Path(p).resolve() for p in snapshot.reads()}


def write_offline_cache(data_dir, design, n_companies=3):
    """A minimal on-disk cache: frame, submissions and prices (benchmarks + all but the last company)."""
    os.makedirs(os.path.join(data_dir, "submissions"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "prices"), exist_ok=True)
    frame = {"data": [{"cik": c, "val": 20e6, "end": f"{design.float_year}-06-30"} for c in range(1, n_companies + 1)]}
    with open(es.frame_path(data_dir, design.float_year), "w") as f:
        json.dump(frame, f)
    p_start, p_end = es.price_window(design)
    days = _bdays(p_start, p_end)
    stamps = [int(datetime(d.year, d.month, d.day, 20, tzinfo=timezone.utc).timestamp()) for d in days]

    def chart(seed):
        rng = random.Random(seed)
        px, closes = 10.0, []
        for _ in days:
            px *= 1 + rng.gauss(0, 0.02)
            closes.append(px)
        return {"chart": {"result": [{"timestamp": stamps, "indicators": {"adjclose": [{"adjclose": closes}]}}]}}

    for sym in ("IWM", "SPY"):
        with open(os.path.join(data_dir, "prices", f"{sym}_{p_start}_{p_end}.json"), "w") as f:
            json.dump(chart(sym), f)
    accepted = [(design.window_start + timedelta(days=30 * k + 3)).isoformat() + "T14:00:00.000Z" for k in range(5)]
    for c in range(1, n_companies + 1):
        sub = {"entityType": "operating", "sic": "1000", "tickers": [f"C{c}"],
               "filings": {"recent": {"form": ["8-K"] * 5, "acceptanceDateTime": accepted,
                                      "filingDate": [a[:10] for a in accepted], "items": ["3.02"] * 5,
                                      "accessionNumber": [f"a{c}{k}" for k in range(5)]}, "files": []}}
        with open(os.path.join(data_dir, "submissions", f"{c}.json"), "w") as f:
            json.dump(sub, f)
        if c != n_companies:
            with open(os.path.join(data_dir, "prices", f"C{c}_{p_start}_{p_end}.json"), "w") as f:
                json.dump(chart(c), f)


def _no_sleep(seconds):
    raise AssertionError("slept in offline mode")


def test_offline_run_design_counts_misses_without_network(no_network, monkeypatch, tmp_path):
    monkeypatch.setattr(es.time, "sleep", _no_sleep)
    design = es.in_sample_design({"nano": 5})
    write_offline_cache(str(tmp_path), design)
    study = es.run_design(design, offline=True, data_dir=str(tmp_path), user_agent="ua")
    cov = study["coverage"]["nano"]
    assert cov["ok"] == 3 and cov["with_prices"] == 2 and cov["offline_miss"] == 1 and cov["events"] == 10
    assert len(snapshot.misses()) == 1 and "C3_" in snapshot.misses()[0]
    with pytest.raises(SystemExit):
        es.check_offline_misses(allow_missing=False)
    es.check_offline_misses(allow_missing=True)


def test_offline_missing_submissions_is_a_miss_not_a_status_change(no_network, tmp_path):
    design = es.in_sample_design({"nano": 5})
    write_offline_cache(str(tmp_path), design)
    os.remove(tmp_path / "submissions" / "2.json")
    ticker, events, status = es.company_events(2, "nano", "ua", str(tmp_path / "submissions"),
                                               window=design.window, offline=True)
    assert (ticker, events, status) == (None, [], es.OFFLINE_MISS)
    assert snapshot.misses()[-1].endswith("2.json")


def test_offline_cli_fails_loudly_and_allow_missing_writes(no_network, monkeypatch, tmp_path):
    from app.config import get_settings

    write_offline_cache(str(tmp_path), es.in_sample_design())
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    only_nano = ["--nano", "5", "--micro", "0", "--small", "0", "--large", "0"]
    with pytest.raises(SystemExit):
        es.main(["--offline", *only_nano])
    assert not (tmp_path / "event_study.json").exists()
    out = tmp_path / "replay.json"
    es.main(["--offline", "--allow-missing", *only_nano, "--output", str(out)])
    study = json.loads(out.read_text())
    assert study["offline_misses"] == 1 and study["inputs_manifest"].startswith("snapshots/")
    manifest = json.loads((tmp_path / study["inputs_manifest"]).read_text())
    assert "public_float_CY2023Q2I.json" in manifest["files"] and manifest["reads_source"] == "registry"
    assert manifest["results_sha256"] == snapshot.results_sha256(study)
    assert not (tmp_path / "event_study.json").exists()
