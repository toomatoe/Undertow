"""The working paper's headline numbers match docs/results, and the frontend copy matches the paper.

Needs the repo root (docs/ and frontend/): scripts/pytest.sh mounts it read-only at /repo, CI runs from a
checkout. Skips only when docs/ is not there (e.g. a bare api image).
"""

import json
import shutil
from pathlib import Path

import pytest

from app.research import paper_numbers
from app.research.paper_numbers import HEADLINE, PAPER, RESULTS_DIR, check, find_repo_root, formatted

ROOT = find_repo_root()
FRONTEND_COPY = "frontend/src/content/working-paper.md"

pytestmark = pytest.mark.skipif(
    not (ROOT / "docs").is_dir(),
    reason=f"repo docs/ not available at {ROOT} (bare api image?); mount the repo at /repo or set AFTERFILE_REPO_ROOT",
)


def test_headline_numbers_match_results_and_paper():
    assert check(ROOT) == []


def test_headline_covers_every_results_file():
    assert len(HEADLINE) >= 12
    files = {c["file"] for c in HEADLINE}
    assert files == {paper_numbers.IN_SAMPLE, paper_numbers.OOS, paper_numbers.INSIDER, paper_numbers.BACKTEST}


def test_frontend_copy_is_identical():
    def norm(p: Path) -> bytes:
        return p.read_bytes().replace(b"\r\n", b"\n")

    assert norm(ROOT / FRONTEND_COPY) == norm(ROOT / PAPER), f"copy {PAPER} to {FRONTEND_COPY}"


def _copy_repo(tmp_path: Path) -> Path:
    (tmp_path / "docs/paper").mkdir(parents=True)
    shutil.copy(ROOT / PAPER, tmp_path / PAPER)
    shutil.copytree(ROOT / RESULTS_DIR, tmp_path / RESULTS_DIR)
    return tmp_path


def test_check_detects_paper_drift(tmp_path):
    root = _copy_repo(tmp_path)
    claim = next(c for c in HEADLINE if c["label"] == "micro cluster 5d excess vs baseline")
    text = formatted(claim)
    paper = root / PAPER
    paper.write_text(paper.read_text(encoding="utf-8").replace(text, "+9.99%"), encoding="utf-8")
    problems = check(root)
    assert any(claim["label"] in p and "not found" in p for p in problems)


def test_check_detects_json_drift(tmp_path):
    root = _copy_repo(tmp_path)
    path = root / RESULTS_DIR / paper_numbers.OOS
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["confirmatory"][0]["t_clustered"] = -3.1
    path.write_text(json.dumps(doc), encoding="utf-8")
    problems = check(root)
    assert any(p.startswith("H1 clustered t:") and "-3.1" in p for p in problems)


def test_find_repo_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AFTERFILE_REPO_ROOT", str(tmp_path))
    assert find_repo_root() == tmp_path
