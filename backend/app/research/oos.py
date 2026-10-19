"""Pre-registered out-of-sample Edge Lab: 2020-10 .. 2023-08, fresh companies.

The design, the three confirmatory hypotheses and the verdict rules are fixed in
PREREGISTRATION_OOS.md (registered 2026-10-19, before any OOS result existed).
This module implements exactly that file; tests/test_oos.py asserts the constants
match. Changing anything here is a new design and needs a new pre-registration.

- Same machinery as the in-sample study (eventstudy.run_design): taxonomy, costs,
  borrow, baseline, winsorizing, benchmarks.
- Sample: frame CY2020Q2, seed 2020, nano 150 / micro 250 / small 250 / large 100,
  excluding every in-sample candidate CIK (frame CY2023Q2, seed 7, 2.5x oversample).
- `confirmatory`: H1-H3 with firm-clustered t-stats against a Bonferroni family of 3.
  Everything in `results[]` is exploratory (full-grid Bonferroni, original rule).

Output: {DATA_DIR}/event_study_oos.json. Never writes event_study.json (live evidence).

Run:  python -m app.research.oos [--offline [--allow-missing]] [--output PATH]
"""

import argparse
import dataclasses
import logging
import os
import statistics
from dataclasses import dataclass
from datetime import date

from app.config import get_settings
from app.pipeline.signals import ALL_SIGNALS
from app.research import snapshot
from app.research.eventstudy import (
    BASELINE,
    BORROW_APR,
    COSTS,
    DEFAULT_SIZES,
    FLOAT_YEAR,
    MIN_N,
    RESULTS_FILE,
    SEED,
    StudyDesign,
    add_replay_args,
    build_study,
    check_offline_misses,
    clustered_t,
    clustered_welch_t,
    collect,
    sample_universe,
    winsor_bounds,
    write_study,
)

log = logging.getLogger("eventstudy.oos")

PREREGISTRATION = "backend/app/research/PREREGISTRATION_OOS.md"
PREREGISTERED_ON = "2026-10-19"
OOS_RESULTS_FILE = "event_study_oos.json"

OOS_DESIGN = StudyDesign(
    name="oos_2020_2023",
    window_start=date(2020, 10, 1),
    window_end=date(2023, 8, 31),
    float_year=2020,
    seed=2020,
    sizes={"nano": 150, "micro": 250, "small": 250, "large": 100},
    exclude_ciks=frozenset(),  # filled at run time by resolve_design(): every in-sample candidate
    results_file=OOS_RESULTS_FILE,
)

# The in-sample candidate list whose CIKs are excluded (including the 2.5x oversample).
EXCLUDE_FROM = {"sizes": dict(DEFAULT_SIZES), "float_year": FLOAT_YEAR, "seed": SEED}

ALPHA = 0.05
FAMILY_SIZE = 3
T_CRIT_CONFIRMATORY = statistics.NormalDist().inv_cdf(1 - ALPHA / (2 * FAMILY_SIZE))  # 2.394
MIN_COMPANIES = 15
REPLICATED, NOT_REPLICATED, UNDERPOWERED = "replicated", "not replicated", "underpowered"


@dataclass(frozen=True)
class Hypothesis:
    id: str
    signal: str
    buckets: tuple[str, ...]
    horizon: int
    direction: str


HYPOTHESES = (
    Hypothesis("H1", "offering_priced", ("nano",), 20, "-"),
    Hypothesis("H2", "unregistered_equity", ("micro", "nano"), 20, "-"),  # 8-K item 3.02, pooled
    Hypothesis("H3", "material_agreement", ("nano",), 20, "-"),  # in-sample "?" lead, now a short
)


def exclusion_ciks(data_dir: str, user_agent: str, offline: bool = False) -> frozenset[int]:
    """Every CIK in the in-sample candidate list. Refuses to continue if it cannot be rebuilt."""
    candidates = sample_universe(EXCLUDE_FROM["sizes"], data_dir, user_agent, EXCLUDE_FROM["seed"],
                                 float_year=EXCLUDE_FROM["float_year"], offline=offline)
    ciks = frozenset(c for ciks in candidates.values() for c in ciks)
    if not ciks:
        raise SystemExit("Cannot rebuild the in-sample candidate list (CY2023Q2 frame missing); "
                         "the fresh-company rule cannot be enforced, so the OOS study will not run")
    return ciks


def resolve_design(data_dir: str, user_agent: str, offline: bool = False) -> StudyDesign:
    return dataclasses.replace(OOS_DESIGN, exclude_ciks=exclusion_ciks(data_dir, user_agent, offline))


def _clip(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])


def confirmatory(measurements: list[dict], t_crit: float = T_CRIT_CONFIRMATORY) -> list[dict]:
    """Evaluate H1-H3 with the pre-registered rules. Comparisons use unrounded statistics.

    Each event is winsorized with its own bucket's 1st/99th percentile bounds (as in summarize)
    and pays its own bucket's cost and borrow; the baseline pools the same buckets.
    """
    bounds = winsor_bounds(measurements)
    out = []
    for h in HYPOTHESES:
        fld = f"drift_{h.horizon}"
        sign = -1 if h.direction == "-" else 1
        events = [m for m in measurements if m["signal"] == h.signal and m["bucket"] in h.buckets]
        base = [m for m in measurements if m["signal"] == BASELINE and m["bucket"] in h.buckets]
        x = [_clip(m[fld], bounds[(m["bucket"], fld)]) for m in events]
        bx = [_clip(m[fld], bounds[(m["bucket"], fld)]) for m in base]
        tickers, base_tickers = [m["ticker"] for m in events], [m["ticker"] for m in base]
        n, companies = len(x), len(set(tickers))
        row = {
            "hypothesis": h.id,
            "signal": h.signal,
            "label": ALL_SIGNALS[h.signal].label,
            "buckets": list(h.buckets),
            "cells": [f"{h.signal}/{b}/{h.horizon}d" for b in h.buckets],
            "horizon_days": h.horizon,
            "direction": h.direction,
            "n": n,
            "companies": companies,
            "mean_abnormal": None,
            "baseline_mean": None,
            "excess_vs_baseline": None,
            "t_clustered": None,
            "t_vs_baseline_clustered": None,
            "mean_net": None,
            "t_critical": round(t_crit, 3),
        }
        checks = {"n": n >= MIN_N, "companies": companies >= MIN_COMPANIES}
        if n:
            mean = statistics.mean(x)
            net = [sign * v - COSTS[m["bucket"]] - (BORROW_APR[m["bucket"]] * h.horizon / 252 if sign < 0 else 0.0)
                   for v, m in zip(x, events)]
            t_c = clustered_t(x, tickers)
            row.update(mean_abnormal=round(mean, 5), mean_net=round(statistics.mean(net), 5), t_clustered=round(t_c, 2))
            checks["t_vs_zero"] = abs(t_c) >= t_crit
            checks["mean_net_positive"] = statistics.mean(net) > 0
            checks["mean_registered_way"] = (mean < 0) if sign < 0 else (mean > 0)
            if bx:
                b_mean = statistics.mean(bx)
                excess = mean - b_mean
                t_b = clustered_welch_t(x, tickers, bx, base_tickers)
                row.update(baseline_mean=round(b_mean, 5), excess_vs_baseline=round(excess, 5),
                           t_vs_baseline_clustered=round(t_b, 2))
                checks["t_vs_baseline"] = abs(t_b) >= t_crit
                checks["excess_registered_way"] = (excess < 0) if sign < 0 else (excess > 0)
        required = ["n", "companies", "t_vs_zero", "t_vs_baseline", "mean_registered_way",
                    "excess_registered_way", "mean_net_positive"]
        if not (checks["n"] and checks["companies"]):
            verdict = UNDERPOWERED
        elif all(checks.get(k, False) for k in required):
            verdict = REPLICATED
        else:
            verdict = NOT_REPLICATED
        row["checks"] = {k: checks.get(k, False) for k in required}
        row["verdict"] = verdict
        out.append(row)
    return out


def build_oos_study(design: StudyDesign, measurements: list[dict], coverage: dict) -> dict:
    study = build_study(design, measurements, coverage)
    study["testing"]["role"] = "exploratory: full-grid Bonferroni, original `significant` rule"
    study["preregistration"] = PREREGISTRATION
    study["preregistered_on"] = PREREGISTERED_ON
    study["confirmatory_testing"] = {
        "family_size": FAMILY_SIZE,
        "alpha_two_sided": ALPHA,
        "t_critical": round(T_CRIT_CONFIRMATORY, 3),
        "min_n": MIN_N,
        "min_companies": MIN_COMPANIES,
        "statistic": "firm-clustered CR1 t (clusters = companies)",
    }
    study["confirmatory"] = confirmatory(measurements)
    study["caveats"].append(
        "Only the three pre-registered hypotheses in `confirmatory` are confirmatory tests. Everything in "
        "results[] is exploratory: a hit there is a lead for a future pre-registered test, not a confirmation."
    )
    return study


def _guard_output(path: str, data_dir: str) -> None:
    live = os.path.abspath(os.path.join(data_dir, RESULTS_FILE))
    if os.path.abspath(path) == live or os.path.basename(path) == RESULTS_FILE:
        raise SystemExit(f"Refusing to write the OOS study to {RESULTS_FILE}: that file is the live evidence")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_replay_args(parser)
    args = parser.parse_args(argv)
    settings = get_settings()
    data_dir = settings.data_dir
    path = args.output or os.path.join(data_dir, OOS_DESIGN.results_file)
    _guard_output(path, data_dir)
    snapshot.start_tracking()
    try:
        design = resolve_design(data_dir, settings.sec_user_agent, args.offline)
        log.info("OOS design %s: excluding %d in-sample candidate CIKs", design.name, len(design.exclude_ciks))
        measurements, coverage = collect(design, offline=args.offline, data_dir=data_dir)
        check_offline_misses(args.allow_missing)
        study = build_oos_study(design, measurements, coverage)
        if args.offline:
            study["offline_misses"] = len(snapshot.misses())
        manifest = write_study(study, path, data_dir)
    finally:
        snapshot.stop_tracking()
    log.info("Wrote %s (manifest %s): %d events, %d exploratory results", path, manifest,
             study["measured_events"], len(study["results"]))
    for c in study["confirmatory"]:
        log.info("%s %-20s %s n=%d companies=%d t_cl=%s t_base_cl=%s net=%s -> %s", c["hypothesis"], c["signal"],
                 "+".join(c["buckets"]), c["n"], c["companies"], c["t_clustered"], c["t_vs_baseline_clustered"],
                 c["mean_net"], c["verdict"].upper())


if __name__ == "__main__":
    main()
