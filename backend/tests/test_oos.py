import json
import random
import statistics
from datetime import date
from pathlib import Path

import pytest

import app.research.eventstudy as es
from app.pipeline.companies import FloatRecord
from app.research import oos

PREREG = Path(oos.__file__).with_name("PREREGISTRATION_OOS.md")


def test_oos_design_matches_preregistration():
    d = oos.OOS_DESIGN
    assert (d.name, d.window_start, d.window_end) == ("oos_2020_2023", date(2020, 10, 1), date(2023, 8, 31))
    assert (d.float_year, d.seed) == (2020, 2020)
    assert dict(d.sizes) == {"nano": 150, "micro": 250, "small": 250, "large": 100}
    assert d.results_file == "event_study_oos.json" != es.RESULTS_FILE
    assert oos.EXCLUDE_FROM == {"sizes": {"nano": 150, "micro": 250, "small": 250, "large": 100},
                                "float_year": 2023, "seed": 7}
    assert [(h.id, h.signal, h.buckets, h.horizon, h.direction) for h in oos.HYPOTHESES] == [
        ("H1", "offering_priced", ("nano",), 20, "-"),
        ("H2", "unregistered_equity", ("micro", "nano"), 20, "-"),
        ("H3", "material_agreement", ("nano",), 20, "-"),
    ]
    assert oos.FAMILY_SIZE == 3 and oos.ALPHA == 0.05
    assert oos.T_CRIT_CONFIRMATORY == pytest.approx(statistics.NormalDist().inv_cdf(1 - 0.05 / 6))
    assert round(oos.T_CRIT_CONFIRMATORY, 3) == 2.394
    assert (oos.MIN_COMPANIES, es.MIN_N) == (15, 20)
    assert oos.PREREGISTRATION == "backend/app/research/PREREGISTRATION_OOS.md"

    text = PREREG.read_text(encoding="utf-8")
    assert "**Date registered:** 2026-10-19" in text and oos.PREREGISTERED_ON == "2026-10-19"
    for needle in ["2020-10-01 to 2023-08-31", "CY2020Q2", "nano 150 / micro 250 / small 250 / large 100",
                   "**2020**", "float_year=2023, seed=7", "offering_priced", "unregistered_equity",
                   "material_agreement", "micro + nano, pooled", "inv_cdf(1 - 0.05 / 6)", "**2.39**", "= 2.394",
                   "n < 20 events **or** companies < 15", "replicated", "not replicated", "underpowered",
                   "oos_2020_2023", "event_study_oos.json"]:
        assert needle in text, needle


def _m(signal, bucket, ticker, d20, rng):
    return {"signal": signal, "bucket": bucket, "ticker": ticker, "reaction": rng.gauss(0, 0.02),
            "drift_5": rng.gauss(0, 0.02), "drift_20": d20}


def _world(event_drift, n_events, n_companies, signal="offering_priced", buckets=("nano",), seed=0):
    rng = random.Random(seed)
    ms = []
    for b in ("nano", "micro"):
        for i in range(300):
            ms.append(_m(es.BASELINE, b, f"{b}{i % 40}", rng.gauss(0.0, 0.05), rng))
    for i in range(n_events):
        b = buckets[i % len(buckets)]
        ms.append(_m(signal, b, f"E{i % n_companies}", event_drift + rng.gauss(0, 0.03), rng))
    return ms


def _row(rows, hid):
    return next(r for r in rows if r["hypothesis"] == hid)


def test_confirmatory_replicated():
    rows = oos.confirmatory(_world(-0.15, 60, 30))
    r = _row(rows, "H1")
    assert r["verdict"] == oos.REPLICATED, r
    assert r["n"] == 60 and r["companies"] == 30 and r["cells"] == ["offering_priced/nano/20d"]
    assert r["t_clustered"] < -oos.T_CRIT_CONFIRMATORY and r["t_vs_baseline_clustered"] < -oos.T_CRIT_CONFIRMATORY
    assert r["mean_net"] > 0 and all(r["checks"].values())
    # No H2/H3 events at all: underpowered, not "not replicated"
    assert _row(rows, "H2")["verdict"] == _row(rows, "H3")["verdict"] == oos.UNDERPOWERED


def test_confirmatory_not_replicated_when_costs_eat_the_drift():
    r = _row(oos.confirmatory(_world(-0.04, 60, 30)), "H1")
    # Drift is negative and may be significant, but -mean - 3% cost - borrow is not positive
    assert r["mean_net"] < 0 and not r["checks"]["mean_net_positive"]
    assert r["verdict"] == oos.NOT_REPLICATED


def test_confirmatory_not_replicated_when_wrong_way():
    r = _row(oos.confirmatory(_world(+0.15, 60, 30)), "H1")
    assert not r["checks"]["mean_registered_way"] and r["verdict"] == oos.NOT_REPLICATED


def test_confirmatory_underpowered_cases():
    few_companies = _row(oos.confirmatory(_world(-0.15, 60, 10)), "H1")
    assert few_companies["companies"] == 10 and few_companies["verdict"] == oos.UNDERPOWERED
    few_events = _row(oos.confirmatory(_world(-0.15, 19, 19)), "H1")
    assert few_events["n"] == 19 and few_events["verdict"] == oos.UNDERPOWERED


def test_confirmatory_h2_pools_micro_and_nano_with_bucket_costs():
    ms = _world(-0.15, 60, 30, signal="unregistered_equity", buckets=("micro", "nano"))
    r = _row(oos.confirmatory(ms), "H2")
    assert r["buckets"] == ["micro", "nano"] and r["n"] == 60
    assert r["cells"] == ["unregistered_equity/micro/20d", "unregistered_equity/nano/20d"]
    events = [m for m in ms if m["signal"] == "unregistered_equity"]
    bounds = es.winsor_bounds(ms)
    net = [-min(max(m["drift_20"], bounds[(m["bucket"], "drift_20")][0]), bounds[(m["bucket"], "drift_20")][1])
           - es.COSTS[m["bucket"]] - es.BORROW_APR[m["bucket"]] * 20 / 252 for m in events]
    assert r["mean_net"] == round(statistics.mean(net), 5)
    assert r["verdict"] == oos.REPLICATED


def test_clustering_can_flip_a_naive_pass():
    """60 events but each firm's single event duplicated: plain t would pass, clustered t decides."""
    rng = random.Random(5)
    ms = _world(0.0, 0, 1)
    for i in range(15):
        d = -0.05 + rng.gauss(0, 0.12)
        for _ in range(4):
            ms.append(_m("offering_priced", "nano", f"E{i}", d, rng))
    r = _row(oos.confirmatory(ms), "H1")
    x = [m["drift_20"] for m in ms if m["signal"] == "offering_priced"]
    assert abs(es.t_stat(x)) > abs(r["t_clustered"])


def test_resolve_design_excludes_every_in_sample_candidate(monkeypatch, tmp_path):
    frames = {2023: {c: FloatRecord(c, 20e6, "2023-06-30") for c in range(1, 2000)},
              2020: {c: FloatRecord(c, 20e6, "2020-06-30") for c in range(1, 2000)}}
    monkeypatch.setattr(es, "fetch_frame", lambda year, *a, **k: frames.get(year, {}))
    design = oos.resolve_design(str(tmp_path), "ua")
    in_sample = es.sample_universe(es.DEFAULT_SIZES, str(tmp_path), "ua", 7, float_year=2023)
    assert design.exclude_ciks == frozenset(c for v in in_sample.values() for c in v)
    assert len(design.exclude_ciks) == int(150 * 2.5)  # only nano exists in this frame: oversample included
    oos_sample = es.sample_universe(design.sizes, str(tmp_path), "ua", design.seed,
                                    float_year=design.float_year, exclude_ciks=design.exclude_ciks)
    assert not set(oos_sample["nano"]) & design.exclude_ciks
    assert design.to_config()["exclude_ciks"]["count"] == len(design.exclude_ciks)

    monkeypatch.setattr(es, "fetch_frame", lambda *a, **k: {})
    with pytest.raises(SystemExit):
        oos.resolve_design(str(tmp_path), "ua")


def test_main_writes_oos_file_and_never_touches_live_evidence(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    live = tmp_path / "event_study.json"
    live.write_text('{"live": true}')
    monkeypatch.setattr(oos, "exclusion_ciks", lambda *a, **k: frozenset({1, 2}))
    seen = {}

    def fake_collect(design, offline=False, data_dir=None, **kw):
        seen.update(design=design, offline=offline)
        return _world(-0.15, 60, 30), {"nano": {"companies": 30}}

    monkeypatch.setattr(oos, "collect", fake_collect)
    oos.main(["--offline"])
    assert live.read_text() == '{"live": true}'
    out = json.loads((tmp_path / "event_study_oos.json").read_text())
    assert seen["offline"] and seen["design"].exclude_ciks == frozenset({1, 2})
    assert out["config"]["study"] == "oos_2020_2023" and out["config"]["window"] == ["2020-10-01", "2023-08-31"]
    assert out["config"]["size_measured"] == "SEC public float, CY2020Q2"
    assert out["preregistration"] == "backend/app/research/PREREGISTRATION_OOS.md"
    assert [c["hypothesis"] for c in out["confirmatory"]] == ["H1", "H2", "H3"]
    for c in out["confirmatory"]:
        assert {"hypothesis", "cells", "n", "companies", "t_clustered", "t_vs_baseline_clustered", "mean_net",
                "verdict"} <= set(c)
    assert out["confirmatory"][0]["verdict"] == "replicated"
    assert out["testing"]["role"].startswith("exploratory")
    assert out["inputs_manifest"].startswith("snapshots/oos_2020_2023_")
    assert any("late 2020 to 2023" in c for c in out["caveats"])

    with pytest.raises(SystemExit):
        oos.main(["--output", str(live)])
    assert live.read_text() == '{"live": true}'
