"""Headline numbers of the working paper, checked against the published result files.

`docs/paper/WORKING_PAPER.md` quotes numbers from `docs/results/*.json`. Each entry in `HEADLINE` names one
quoted number: the file, how to find it (a results row by signal/bucket/horizon, a row of another list, or a
dotted JSON path), the field, the value as quoted, a tolerance, and a format string. `check()` returns a list
of mismatches (empty = paper and JSON agree):

- the JSON value must equal `value` within `tolerance` (strings must match exactly), and
- `fmt.format(value)` (for example "+1.66%" or "t = 3.29") must appear literally in the paper.

Rule: change a number in the paper -> update HEADLINE (and the other way round). Pure stdlib, no app imports,
so the test runs in any image that can see the repo root.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

PAPER = "docs/paper/WORKING_PAPER.md"
RESULTS_DIR = "docs/results"

IN_SAMPLE = "event_study_2026-10-15.json"
OOS = "event_study_oos_2026-10-19.json"
INSIDER = "event_study_insider_purchases_2026-10-19.json"
BACKTEST = "backtest_2026-10-16.json"

# Rounded values in the JSON are 3-5 decimals; tolerances only absorb float representation.
_EPS = 1e-9


def _row(signal: str, bucket: str, horizon: int) -> dict[str, Any]:
    return {"signal": signal, "bucket": bucket, "horizon_days": horizon}


HEADLINE: list[dict[str, Any]] = [
    # --- In-sample event study (abstract, Table 1, section 4.1) ---
    {"label": "in-sample measured events", "file": IN_SAMPLE, "selector": {"path": ""},
     "field": "measured_events", "value": 21842, "tolerance": 0, "fmt": "{:,}"},
    {"label": "in-sample Bonferroni t_critical", "file": IN_SAMPLE, "selector": {"path": "testing"},
     "field": "t_critical", "value": 3.49, "tolerance": _EPS, "fmt": "|t| ≥ {:.2f}"},
    {"label": "in-sample number of tests", "file": IN_SAMPLE, "selector": {"path": "testing"},
     "field": "n_tests", "value": 102, "tolerance": 0, "fmt": "{} tests"},
    {"label": "nano offering 20d n", "file": IN_SAMPLE, "selector": _row("offering_priced", "nano", 20),
     "field": "n", "value": 302, "tolerance": 0, "fmt": "n = {}"},
    {"label": "nano offering 20d mean abnormal", "file": IN_SAMPLE, "selector": _row("offering_priced", "nano", 20),
     "field": "mean_abnormal", "value": -0.15632, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "nano offering 20d t", "file": IN_SAMPLE, "selector": _row("offering_priced", "nano", 20),
     "field": "t_stat", "value": -6.67, "tolerance": _EPS, "fmt": "t = {:.2f}"},
    {"label": "nano offering 20d excess vs baseline", "file": IN_SAMPLE,
     "selector": _row("offering_priced", "nano", 20),
     "field": "excess_vs_baseline", "value": -0.13672, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "nano offering 20d mean net", "file": IN_SAMPLE, "selector": _row("offering_priced", "nano", 20),
     "field": "mean_net", "value": 0.08664, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "nano offering 20d significant", "file": IN_SAMPLE, "selector": _row("offering_priced", "nano", 20),
     "field": "significant", "value": True, "tolerance": 0, "fmt": None},
    # --- Pre-registered OOS replication (abstract, Table 2, section 4.2, conclusion) ---
    {"label": "OOS measured events", "file": OOS, "selector": {"path": ""},
     "field": "measured_events", "value": 21223, "tolerance": 0, "fmt": "{:,}"},
    {"label": "OOS confirmatory t_critical", "file": OOS, "selector": {"path": "confirmatory_testing"},
     "field": "t_critical", "value": 2.394, "tolerance": _EPS, "fmt": "{:.3f}"},
    {"label": "H1 n", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H1"},
     "field": "n", "value": 228, "tolerance": 0, "fmt": "| {} |"},
    {"label": "H1 clustered t", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H1"},
     "field": "t_clustered", "value": -2.64, "tolerance": _EPS, "fmt": "t = {:.2f}"},
    {"label": "H1 excess vs baseline", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H1"},
     "field": "excess_vs_baseline", "value": -0.07566, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "H1 mean net", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H1"},
     "field": "mean_net", "value": -0.00057, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "H1 verdict", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H1"},
     "field": "verdict", "value": "not replicated", "tolerance": 0, "fmt": '"{}"'},
    {"label": "H2 clustered t", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H2"},
     "field": "t_clustered", "value": -0.76, "tolerance": _EPS, "fmt": "t = {:.2f}"},
    {"label": "H2 verdict", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H2"},
     "field": "verdict", "value": "not replicated", "tolerance": 0, "fmt": None},
    {"label": "H3 clustered t", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H3"},
     "field": "t_clustered", "value": -0.93, "tolerance": _EPS, "fmt": "t = {:.2f}"},
    {"label": "H3 verdict", "file": OOS, "selector": {"list": "confirmatory", "hypothesis": "H3"},
     "field": "verdict", "value": "not replicated", "tolerance": 0, "fmt": None},
    # --- Insider purchases (abstract, Table 4, section 4.3, conclusion) ---
    {"label": "insider Bonferroni t_critical", "file": INSIDER, "selector": {"path": "testing"},
     "field": "t_critical", "value": 3.16, "tolerance": _EPS, "fmt": "{:.2f}"},
    {"label": "insider number of tests", "file": INSIDER, "selector": {"path": "testing"},
     "field": "n_tests", "value": 32, "tolerance": 0, "fmt": "{} cells"},
    {"label": "micro cluster 5d n", "file": INSIDER, "selector": _row("insider_cluster_purchase", "micro", 5),
     "field": "n", "value": 662, "tolerance": 0, "fmt": "n = {}"},
    {"label": "micro cluster 5d firms", "file": INSIDER, "selector": _row("insider_cluster_purchase", "micro", 5),
     "field": "companies", "value": 177, "tolerance": 0, "fmt": "{} firms"},
    {"label": "micro cluster 5d excess vs baseline", "file": INSIDER,
     "selector": _row("insider_cluster_purchase", "micro", 5),
     "field": "excess_vs_baseline", "value": 0.01662, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "micro cluster 5d clustered t", "file": INSIDER,
     "selector": _row("insider_cluster_purchase", "micro", 5),
     "field": "t_stat_clustered", "value": 3.29, "tolerance": _EPS, "fmt": "t = {:.2f}"},
    {"label": "micro cluster 5d mean net", "file": INSIDER, "selector": _row("insider_cluster_purchase", "micro", 5),
     "field": "mean_net", "value": 0.00109, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "micro cluster 5d significant", "file": INSIDER,
     "selector": _row("insider_cluster_purchase", "micro", 5),
     "field": "significant", "value": True, "tolerance": 0, "fmt": None},
    {"label": "insider XML cross-check match rate", "file": INSIDER, "selector": {"path": "data_quality"},
     "field": "match_rate", "value": 1, "tolerance": _EPS, "fmt": "{:.0%} match rate"},
    # --- Backtest (abstract, Table 5, section 5, conclusion) ---
    {"label": "backtest A total return", "file": BACKTEST, "selector": {"path": "periods.A.metrics"},
     "field": "total_return", "value": -0.3336, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "backtest A Sharpe", "file": BACKTEST, "selector": {"path": "periods.A.metrics"},
     "field": "sharpe", "value": -1.24, "tolerance": _EPS, "fmt": "Sharpe {:.2f}"},
    {"label": "backtest B total return", "file": BACKTEST, "selector": {"path": "periods.B.metrics"},
     "field": "total_return", "value": -0.1145, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "backtest A gross average trade", "file": BACKTEST, "selector": {"path": "periods.A.waterfall[0]"},
     "field": "avg_trade_return", "value": 0.0465, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "backtest A final average trade", "file": BACKTEST, "selector": {"path": "periods.A.metrics"},
     "field": "avg_trade_return", "value": -0.0555, "tolerance": _EPS, "fmt": "{:+.2%}"},
    {"label": "backtest B break-even borrow", "file": BACKTEST, "selector": {"path": "key_finding"},
     "field": "breakeven_apr_B", "value": 0.758, "tolerance": _EPS, "fmt": "{:.1%}"},
    {"label": "IBKR median borrow fee", "file": BACKTEST, "selector": {"path": "borrow_check"},
     "field": "fee_median", "value": 0.0745, "tolerance": _EPS, "fmt": "{:.2%}"},
]

_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def find_repo_root() -> Path:
    """Repo root: env UNDERTOW_REPO_ROOT, else /repo (scripts/pytest.sh mount), else three levels above app/."""
    env = os.environ.get("UNDERTOW_REPO_ROOT")
    if env:
        return Path(env)
    mounted = Path("/repo")
    if (mounted / "docs").is_dir():
        return mounted
    return Path(__file__).resolve().parents[3]


def resolve_path(doc: Any, path: str) -> Any:
    """Follow a dotted path with [i] indices, e.g. "periods.A.waterfall[0]". "" returns the document."""
    node = doc
    for key, index in _PATH_TOKEN.findall(path):
        node = node[int(index)] if index else node[key]
    return node


def select(doc: dict[str, Any], selector: dict[str, Any]) -> Any:
    """The object a selector points at: {"path": ...}, or {"list": name (default "results"), **match}."""
    if "path" in selector:
        return resolve_path(doc, selector["path"])
    match = {k: v for k, v in selector.items() if k != "list"}
    rows = [r for r in doc[selector.get("list", "results")] if all(r.get(k) == v for k, v in match.items())]
    if len(rows) != 1:
        raise LookupError(f"{len(rows)} rows match {selector}")
    return rows[0]


def formatted(claim: dict[str, Any]) -> str | None:
    """The literal string the paper must contain for this claim (None: not checked in the text)."""
    fmt = claim.get("fmt")
    return fmt.format(claim["value"]) if fmt else None


def _value_matches(actual: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool) or isinstance(expected, str):
        return actual == expected
    if not isinstance(actual, (int, float)):
        return False
    return abs(actual - expected) <= tolerance


def check(repo_root: Path | str | None = None) -> list[str]:
    """Mismatches between HEADLINE, the result files and the paper text. Empty list = all good."""
    root = Path(repo_root) if repo_root is not None else find_repo_root()
    problems: list[str] = []
    paper_path = root / PAPER
    try:
        paper = paper_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError as exc:
        return [f"cannot read {paper_path}: {exc}"]

    docs: dict[str, Any] = {}
    for claim in HEADLINE:
        label = claim["label"]
        name = claim["file"]
        if name not in docs:
            try:
                docs[name] = json.loads((root / RESULTS_DIR / name).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                docs[name] = exc
        doc = docs[name]
        if isinstance(doc, Exception):
            problems.append(f"{label}: cannot load {name}: {doc}")
            continue
        try:
            actual = select(doc, claim["selector"])[claim["field"]]
        except (KeyError, IndexError, LookupError, TypeError) as exc:
            problems.append(f"{label}: {name} {claim['selector']} {claim['field']} not found ({exc!r})")
            continue
        if not _value_matches(actual, claim["value"], claim["tolerance"]):
            problems.append(f"{label}: {name} has {actual!r}, HEADLINE says {claim['value']!r}")
        text = formatted(claim)
        if text is not None and text not in paper:
            problems.append(f"{label}: {text!r} not found in {PAPER}")
    return problems


if __name__ == "__main__":  # python -m app.research.paper_numbers
    issues = check()
    print("\n".join(issues) if issues else f"OK: {len(HEADLINE)} headline numbers match")
    raise SystemExit(1 if issues else 0)
