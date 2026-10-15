from datetime import date, datetime, timedelta

from app.pipeline.companies import bucket_for, parse_frame
from app.pipeline.signals import signals_for_filing
from app.research.eventstudy import ET, Event, day0_index, measure, summarize
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
