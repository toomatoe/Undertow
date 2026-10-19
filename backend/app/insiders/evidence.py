"""Evidence row for the live insider_cluster_purchase forward test (app.insiders.live).

The forward test checks one pre-registered in-sample finding: insider_cluster_purchase, micro, 5 trading days.
Its evidence comes from the insider study's own output: {data_dir}/event_study_insider_purchases.json when it
exists (the micro / 5-day row of that signal), else the frozen copy of that row bundled in
forward_test_evidence.json (copied verbatim from docs/results/event_study_insider_purchases_2026-10-19.json).
Never from the main study's event_study.json.
"""

import json
import logging
import os

from app.insiders import study

log = logging.getLogger("insiders.evidence")

BUNDLED_FILE = os.path.join(os.path.dirname(__file__), "forward_test_evidence.json")
SIGNAL = study.CLUSTER
BUCKET = "micro"
HORIZON = 5
STUDY = "insider_purchases"


def _find_row(results: list) -> dict | None:
    for r in results or []:
        if isinstance(r, dict) and r.get("signal") == SIGNAL and r.get("bucket") == BUCKET and r.get("horizon_days") == HORIZON:
            return r
    return None


def bundled_row() -> dict:
    with open(BUNDLED_FILE, encoding="utf-8") as f:
        return json.load(f)["row"]


def load_forward_test_row(data_dir: str) -> tuple[dict | None, str]:
    """(row, origin) with origin 'data_dir' or 'bundled'. The DATA_DIR study wins when it has the row."""
    path = os.path.join(data_dir, study.INSIDER_RESULTS_FILE)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and (row := _find_row(data.get("results"))) is not None:
                return row, "data_dir"
        except (OSError, ValueError) as exc:
            log.warning("Insider study unreadable, using the bundled evidence row: %s", exc)
    try:
        return bundled_row(), "bundled"
    except (OSError, ValueError, KeyError) as exc:
        log.warning("Bundled forward-test evidence unreadable: %s", exc)
        return None, "missing"
