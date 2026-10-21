"""Obsidian vault export (app/vault): rendering, safety, idempotence, immutability, read-back.

tmp dirs + in-memory SQLite; nothing here touches the network (company_profile and httpx are patched to fail).
"""

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import yaml
from sqlalchemy import select

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.fundamentals import service as fundamentals
from app.models import Article, ArticleTicker, Company, JournalEntry, WatchlistItem
from app.newsletter import service as nl
from app.research.paper_numbers import PAPER, find_repo_root
from app.vault import (
    EXPORT_LOCK,
    ExportResult,
    count_conflicts,
    export_vault,
    make_evidence_fn,
    read_state,
    read_theses,
)
from app.vault import exporter, frontmatter, fs, writer

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
PACKAGE = Path(exporter.__file__).parent
ACC_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000123/0000000001-26-000123-index.htm"


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


_n = 0


def article(sym, form, signals, severity, when, url=None, title=None, snippet="Short filing summary text.", ai_summary=None):
    global _n
    _n += 1
    a = Article(
        url=url or f"https://www.sec.gov/Archives/edgar/data/9/{_n:018d}/{_n:010d}-26-{_n:06d}-index.htm",
        url_hash=f"h{_n}", title_hash=f"t{_n}", title=title or f"{form}: {sym} Corp", snippet=snippet,
        ai_summary=ai_summary, source="edgar", source_name="SEC EDGAR", published_at=when, form=form,
        signals=signals, severity=severity, body="FULL FILING BODY SHOULD NEVER APPEAR",
    )
    a.tickers = [ArticleTicker(symbol=sym, method="edgar")]
    return a


PAPER_RESULT = {
    "assumptions": {"starting_capital": 200_000},
    "equity_curve": [{"date": "2026-10-19", "equity": 200_000.0}, {"date": "2026-10-20", "equity": 201_000.0},
                     {"date": "2026-10-21", "equity": 202_500.0}],
}


def paper_fn():
    return PAPER_RESULT


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call from the vault export")

    monkeypatch.setattr(fundamentals, "company_profile", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "event_study.json").write_text(json.dumps({"generated_at": "2026-10-15T20:21:42+00:00", "results": [
        {"signal": "delisting_notice", "bucket": "nano", "horizon_days": 20, "n": 140, "mean_abnormal": -0.081,
         "excess_vs_baseline": -0.05, "t_stat": -4.2, "mean_net": 0.05, "significant": True},
        {"signal": "delisting_notice", "bucket": "nano", "horizon_days": 5, "n": 140, "mean_abnormal": -0.03,
         "t_stat": -2.0, "significant": False},
        {"signal": "offering_priced", "bucket": "micro", "horizon_days": 20, "n": 90, "mean_abnormal": -0.02,
         "t_stat": -1.1, "mean_net": 0.004, "significant": False},
    ]}))
    (d / "companyfacts").mkdir()
    (d / "companyfacts" / "1.json").write_text(json.dumps({"facts": {"us-gaap": {
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": "2026-06-30", "val": 5_000_000, "filed": "2026-08-01"}]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": -12_000_000, "filed": "2026-03-01"}]}},
    }}}))
    (d / "newsletters").mkdir()
    (d / "newsletters" / "2026-W41.json").write_text(json.dumps({
        "id": "2026-W41", "title": "Small-Cap Filing Radar", "week_start": "2026-10-05", "week_end": "2026-10-11",
        "generated_at": "2026-10-12T06:00:00+00:00", "headline": "x"}))
    (d / "newsletters" / "2026-W41.md").write_text("# Small-Cap Filing Radar\n\nArchived issue text.\n")
    return str(d)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "sentinel.md").write_text("human root note\n")
    (v / "Ideas").mkdir()
    (v / "Ideas" / "mine.md").write_text("---\ntitle: mine\n---\nmy own text\n")
    return str(v)


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([
            Company(symbol="TINY", cik=1, name="Tiny Therapeutics", size_bucket="nano", public_float=20_000_000),
            Company(symbol="MICR", cik=2, name="Micro Devices", size_bucket="micro", public_float=120_000_000),
        ])
        s.add(WatchlistItem(symbol="WATCH"))
        a1 = article("TINY", "8-K", ["delisting_notice", "officer_change"], 3, utc(2026, 10, 19, 14), url=ACC_URL,
                     title="8-K: Tiny Therapeutics (items 3.01, 5.02)", snippet="Nasdaq notice " + "word " * 300)
        s.add_all([
            a1,
            article("MICR", "424B4", ["offering_priced"], 2, utc(2026, 10, 21, 13)),
            article("TINY", "4", ["insider_cluster_purchase"], 2, utc(2026, 10, 18, 20)),
            article("OLDC", "8-K", ["bankruptcy"], 3, utc(2026, 8, 1, 12)),  # outside the 30-day window
        ])
        news = Article(url="https://news/1", url_hash="n1", title_hash="n1", title="Tiny news", source="rss",
                       source_name="X", published_at=utc(2026, 10, 20, 15))
        news.tickers = [ArticleTicker(symbol="NEWS", method="cashtag")]
        s.add(news)
        s.flush()
        s.add(JournalEntry(article_id=a1.id, ticker="TINY", cik=1, form="8-K", signals=["delisting_notice", "officer_change"],
                           primary_signal="delisting_notice", direction="-", severity=3, size_bucket="nano",
                           public_float=20_000_000, filed_at=utc(2026, 10, 19, 14), created_at=utc(2026, 10, 19, 14, 5),
                           status="open", abn_1=0.01))
        s.commit()


def run(vault_dir, data_dir, now=NOW, **kw):
    kw.setdefault("evidence_fn", make_evidence_fn(data_dir))
    kw.setdefault("paper_fn", paper_fn)
    with SessionLocal() as s, EXPORT_LOCK:
        return export_vault(s, vault_dir=vault_dir, data_dir=data_dir, now=now, **kw)


def root(vault_dir) -> Path:
    return Path(vault_dir) / "Undertow"


def read_fm(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    _, fm_text, body = text.split("---\n", 2)
    return yaml.safe_load(fm_text), body


def snapshot(base: Path, exclude_undertow=False) -> dict[str, tuple[bytes, int]]:
    out = {}
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if exclude_undertow and rel.parts[0] == "Undertow":
            continue
        if p.is_file():
            out[str(rel)] = (p.read_bytes(), p.stat().st_mtime_ns)
    return out


SIGNAL_STEM = "2026-10-19-TINY-8-K-000123"


# --- rendering ----------------------------------------------------------------------------------------------------


def test_export_renders_every_note_type(vault, data_dir):
    res = run(vault, data_dir)
    assert res.errors == 0, res.to_dict()
    assert res.conflicts == 0
    u = root(vault)

    sig, body = read_fm(u / "Signals" / f"{SIGNAL_STEM}.md")
    assert sig["type"] == "signal" and sig["source"] == "undertow"
    assert sig["ticker"] == "[[TINY]]"
    assert sig["form"] == "8-K" and sig["items"] == ["3.01", "5.02"]
    assert sig["accession"] == "0000000001-26-000123"
    assert sig["edgar_url"] == ACC_URL
    assert sig["signals"] == ["delisting_notice", "officer_change"]
    assert sig["signal_names"][0] == "Delisting notice"
    assert sig["direction"] == "-" and sig["severity"] == 3 and sig["size_bucket"] == "nano"
    assert sig["bucket"] == "nano" and sig["horizon_days"] == 20 and sig["n"] == 140
    assert sig["mean_abnormal"] == -0.081 and sig["net"] == 0.05 and sig["significant"] is True
    assert "t_stat_clustered" in sig and sig["forward_test"] is False
    assert sig["journal_id"] == 1
    assert isinstance(sig["generated_at"], datetime) and isinstance(sig["filed_at"], datetime)
    assert "Historical event-study result (hypothetical, not a forecast)" in body
    assert ACC_URL in body
    assert "FULL FILING BODY" not in body
    excerpt = next(line for line in body.splitlines() if line.startswith("> "))
    assert len(excerpt) <= 505

    fwd, fwd_body = read_fm(next((u / "Signals").glob("2026-10-18-TINY-4-*.md")))
    assert fwd["forward_test"] is True
    assert fwd["mean_abnormal"] is None  # no evidence for the nano bucket (the insider row is micro)
    assert "Forward test of a pre-registered finding" in fwd_body
    assert not list((u / "Signals").glob("*OLDC*")), "filings outside the lookback window get no note"
    assert not list((u / "Signals").glob("*NEWS*")), "news without signals gets no note"

    tick, tbody = read_fm(u / "Tickers" / "TINY.md")
    assert tick["type"] == "ticker" and tick["ticker"] == "TINY" and tick["cik"] == 1
    assert tick["company"] == "Tiny Therapeutics" and tick["size_bucket"] == "nano"
    assert tick["public_float_usd"] == 20_000_000 and tick["last_filing"] == date(2026, 10, 19)
    assert tick["active_signals"][0] == "delisting_notice" and "insider_cluster_purchase" in tick["active_signals"]
    assert tick["journal_open"] == 1
    block = writer.extract_block(tbody)
    assert hashlib.sha256(block.encode()).hexdigest() == tick["undertow_hash"]
    assert f"[[{SIGNAL_STEM}]]" in block
    assert "$5.0M as of 2026-06-30" in block and "about 5.0 months" in block  # cached XBRL only
    assert tbody.rstrip().endswith("## My notes")
    assert (u / "Tickers" / "WATCH.md").exists(), "watchlist symbols get a note"
    assert (u / "Tickers" / "MICR.md").exists()
    assert not (u / "Tickers" / "OLDC.md").exists() and not (u / "Tickers" / "NEWS.md").exists()
    watch, wbody = read_fm(u / "Tickers" / "WATCH.md")
    assert watch["company"] is None and watch["watchlist"] is True and "No signal filings" in wbody

    j, jbody = read_fm(u / "Journal" / "1.md")
    assert j["type"] == "journal" and j["entry_id"] == 1 and j["day"] == date(2026, 10, 19)
    assert j["ticker"] == "[[TINY]]" and j["signal"] == "delisting_notice" and j["horizon_days"] == 20
    assert j["expected"] == -0.081 and j["sealed_day"] is None and j["seal_hash"] is None
    assert j["outcome_status"] == "open" and j["outcome_abn_1"] == 0.01 and j["outcome_abn_20"] is None
    assert "hypothetical" in j["outcome_label"].lower()
    assert j["filed_at"] == "2026-10-19T14:00:00.000000Z"  # canonical_entry form, as sealed in the hash chain
    assert hashlib.sha256(writer.extract_block(jbody).encode()).hexdigest() == j["outcome_hash"]

    b, bbody = read_fm(u / "Briefs" / "2026-10-21.md")
    assert b["type"] == "brief" and b["date"] == date(2026, 10, 21)
    assert b["signals_count"] == 1 and b["tickers"] == ["MICR"] and b["forward_test_signals"] == 0
    assert b["paper_portfolio_value"] == 202_500.0 and b["paper_portfolio_return"] == pytest.approx(0.0125)
    assert "hypothetical" in b["paper_label"].lower()
    assert "Hypothetical paper portfolio value" in bbody
    past, pbody = read_fm(u / "Briefs" / "2026-10-19.md")
    assert past["signals_count"] == 1 and "[[Undertow/Journal/1|Journal 1]]" in pbody
    assert read_fm(u / "Briefs" / "2026-10-18.md")[0]["forward_test_signals"] == 1

    st, sbody = read_fm(u / "Studies" / "main.md")
    assert st["type"] == "study" and st["n_results"] == 3 and st["n_significant"] == 1
    assert "[[working-paper]]" in sbody and "hypothetical, not a forecast" in sbody
    assert not (u / "Studies" / "oos.md").exists()

    news_fm, news_body = read_fm(u / "Newsletter" / "2026-W41.md")
    assert news_fm["type"] == "newsletter" and news_fm["issue_id"] == "2026-W41"
    assert "Archived issue text." in news_body

    assert (u / "Paper" / "working-paper.md").read_bytes() == (PACKAGE / "working_paper.md").read_bytes().replace(b"\r\n", b"\n")
    assert sorted(p.name for p in (u / "Bases").iterdir()) == ["Briefs.base", "Journal.base", "Signals.base", "Tickers.base"]
    assert (u / "AGENTS.md").read_text().startswith("# Undertow/")
    assert "AGENTS.md" in (u / "CLAUDE.md").read_text()
    idx, ibody = read_fm(u / "index.md")
    assert idx["type"] == "index" and "[[Undertow/Signals/" in ibody
    log_lines = (u / "log.md").read_text().splitlines()
    assert re.fullmatch(r"- \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z created=\d+ updated=0 unchanged=0 conflicts=0 errors=0", log_lines[-1])
    assert res.counts["Signals"] == 3 and res.counts["Tickers"] == 3 and res.counts["Journal"] == 1


def test_every_note_frontmatter_parses_with_safe_load(vault, data_dir):
    run(vault, data_dir)
    u = root(vault)
    for p in u.rglob("*.md"):
        if p.name in ("log.md", "AGENTS.md", "CLAUDE.md") or p.parent.name == "Paper":
            continue
        meta, _ = read_fm(p)
        assert meta["source"] == "undertow" and meta["type"] in {"signal", "ticker", "journal", "brief", "study", "newsletter", "index"}
        assert "generated_at" in meta
        assert all(re.fullmatch(r"[a-z0-9_]+", k) for k in meta), p


def test_base_files_parse_as_yaml():
    for p in (PACKAGE / "bases").glob("*.base"):
        doc = yaml.safe_load(p.read_text())
        assert isinstance(doc["filters"]["and"], list) and len(doc["filters"]["and"]) == 2
        assert any("file.inFolder(\"Undertow/" in f for f in doc["filters"]["and"])
        view = doc["views"][0]
        assert view["type"] == "table" and view["name"] and view["order"][0] == "file.name"
        assert view["sort"][0]["direction"] == "DESC" and isinstance(view["limit"], int)


# --- idempotence, preservation, conflicts ----------------------------------------------------------------------


def test_second_export_is_a_no_op(vault, data_dir):
    first = run(vault, data_dir)
    assert first.created > 0
    before = snapshot(root(vault))
    second = run(vault, data_dir, now=NOW + timedelta(minutes=15))
    assert (second.created, second.updated, second.conflicts, second.errors) == (0, 0, 0, 0), second.to_dict()
    assert second.unchanged > 0
    assert snapshot(root(vault)) == before  # same bytes and mtimes, log.md included
    state = read_state(data_dir)
    assert state["last_export"]["created"] == 0
    json.dumps(second.to_dict())


def test_my_notes_and_human_keys_survive_reexport(vault, data_dir):
    run(vault, data_dir)
    p = root(vault) / "Tickers" / "TINY.md"
    text = p.read_text()
    text = text.replace("---\n", "---\nmy_rating: 3\n", 1) + "My own reasoning about TINY.\n"
    p.write_text(text)
    with SessionLocal() as s:
        s.add(article("TINY", "8-K", ["auditor_change"], 2, utc(2026, 10, 20, 12)))
        s.commit()
    res = run(vault, data_dir, now=NOW + timedelta(minutes=15))
    assert res.conflicts == 0 and res.updated >= 1
    meta, body = read_fm(p)
    assert meta["my_rating"] == 3
    assert "auditor_change" in meta["active_signals"]
    assert "Auditor change" in writer.extract_block(body)
    assert body.endswith("## My notes\n\nMy own reasoning about TINY.\n")
    assert hashlib.sha256(writer.extract_block(body).encode()).hexdigest() == meta["undertow_hash"]
    assert meta["generated_at"] == datetime(2026, 10, 21, 15, 15, tzinfo=timezone.utc)


def test_edit_inside_fence_writes_conflict_and_leaves_note_untouched(vault, data_dir):
    run(vault, data_dir)
    p = root(vault) / "Tickers" / "TINY.md"
    edited = p.read_text().replace("## Edge Lab evidence", "## Edge Lab evidence\nI edited this line.")
    p.write_text(edited)
    original = p.read_bytes()
    with SessionLocal() as s:
        s.add(article("TINY", "8-K", ["auditor_change"], 2, utc(2026, 10, 20, 12)))
        s.commit()
    res = run(vault, data_dir, now=NOW + timedelta(minutes=15))
    assert res.conflicts == 1 and res.errors == 0
    assert p.read_bytes() == original
    conflicts = list((root(vault) / "_conflicts").glob("TINY-*.md"))
    assert len(conflicts) == 1 and res.conflict_paths == [f"Undertow/_conflicts/{conflicts[0].name}"]
    assert "Auditor change" in conflicts[0].read_text()
    assert count_conflicts(vault) == 1
    assert "conflicts=1" in (root(vault) / "log.md").read_text().splitlines()[-1]
    # A later run with the same pending conflict does not pile up identical conflict files
    again = run(vault, data_dir, now=NOW + timedelta(minutes=30))
    assert again.conflicts == 1 and count_conflicts(vault) == 1 and p.read_bytes() == original


# --- immutability ------------------------------------------------------------------------------------------------


def _chunks(path: Path) -> dict:
    fm_text, _ = frontmatter.split(path.read_text())
    return dict(frontmatter.chunks(fm_text))


def test_journal_sealed_fields_immutable_outcome_updates(vault, data_dir):
    run(vault, data_dir)
    p = root(vault) / "Journal" / "1.md"
    before = _chunks(p)
    head_before = p.read_text().split(writer.BEGIN)[0].split("---\n", 2)[2]
    with SessionLocal() as s:
        e = s.get(JournalEntry, 1)
        e.status, e.abn_5, e.abn_20, e.entry_date = "complete", 0.02, -0.05, date(2026, 10, 20)
        e.size_bucket = "micro"  # a record-time field changed in the DB must never reach the sealed note
        s.commit()
    with open(os.path.join(data_dir, "journal_chain.jsonl"), "w") as f:
        f.write(json.dumps({"day": "2026-10-19", "prev_hash": "0" * 64, "hash": "a" * 64, "count": 1,
                            "sealed_at": "2026-10-20T00:05:00Z", "sealed_late": False}) + "\n")
    res = run(vault, data_dir, now=NOW + timedelta(minutes=15))
    assert res.conflicts == 0 and res.errors == 0
    after = _chunks(p)
    for k, v in before.items():
        if k.startswith("outcome_") or k in ("sealed_day", "seal_hash"):
            continue
        assert after[k] == v, k
    meta, body = read_fm(p)
    assert meta["size_bucket"] == "nano" and meta["generated_at"] == datetime(2026, 10, 21, 15, tzinfo=timezone.utc)
    assert meta["sealed_day"] == date(2026, 10, 19) and meta["seal_hash"] == "a" * 64  # filled once
    assert meta["outcome_status"] == "complete" and meta["outcome_resolved"] is True
    assert meta["outcome_abn_20"] == -0.05 and meta["outcome_entry_date"] == date(2026, 10, 20)
    assert "-5.0%" in writer.extract_block(body)
    assert p.read_text().split(writer.BEGIN)[0].split("---\n", 2)[2] == head_before
    # Seal fields never change again once set
    with open(os.path.join(data_dir, "journal_chain.jsonl"), "w") as f:
        f.write(json.dumps({"day": "2026-10-19", "prev_hash": "0" * 64, "hash": "b" * 64}) + "\n")
    run(vault, data_dir, now=NOW + timedelta(minutes=30))
    assert read_fm(p)[0]["seal_hash"] == "a" * 64


def test_signal_notes_are_never_rewritten(vault, data_dir):
    run(vault, data_dir)
    p = root(vault) / "Signals" / f"{SIGNAL_STEM}.md"
    p.write_text(p.read_text() + "\nhuman addition\n")
    original = p.read_bytes()
    with SessionLocal() as s:
        art = s.scalars(select(Article).where(Article.url == ACC_URL)).one()
        art.snippet, art.ai_summary, art.severity = "changed", "changed summary", 1
        s.commit()
    res = run(vault, data_dir, now=NOW + timedelta(minutes=15))
    assert res.conflicts == 0
    assert p.read_bytes() == original


def test_past_brief_frozen_today_refreshed(vault, data_dir):
    run(vault, data_dir)
    past = root(vault) / "Briefs" / "2026-10-19.md"
    today = root(vault) / "Briefs" / "2026-10-21.md"
    past_bytes = past.read_bytes()
    with SessionLocal() as s:
        s.add(article("MICR", "S-3", ["shelf_registered"], 1, utc(2026, 10, 19, 16)))
        s.add(article("TINY", "8-K", ["auditor_change"], 2, utc(2026, 10, 21, 14)))
        s.commit()
    run(vault, data_dir, now=NOW + timedelta(minutes=15))
    assert past.read_bytes() == past_bytes
    meta, _ = read_fm(today)
    assert meta["signals_count"] == 2 and meta["tickers"] == ["MICR", "TINY"]


def test_brief_prose_has_no_banned_words(vault, data_dir):
    run(vault, data_dir)
    briefs = list((root(vault) / "Briefs").glob("*.md"))
    assert briefs
    for p in briefs:
        _, body = read_fm(p)
        assert nl.banned_words(body) == [], p


def test_brief_line_with_banned_word_is_dropped(vault, data_dir, monkeypatch, caplog):
    monkeypatch.setattr(exporter, "PAPER_LABEL", "Simulated profit figure")
    run(vault, data_dir)
    _, body = read_fm(root(vault) / "Briefs" / "2026-10-21.md")
    assert "profit" not in body.lower() and "Hypothetical paper portfolio value" not in body
    assert any("banned words" in r.getMessage() for r in caplog.records if r.levelname == "ERROR")


# --- safety ------------------------------------------------------------------------------------------------------


def test_nothing_written_outside_undertow(vault, data_dir):
    before = snapshot(Path(vault), exclude_undertow=True)
    run(vault, data_dir)
    run(vault, data_dir, now=NOW + timedelta(minutes=15))
    assert snapshot(Path(vault), exclude_undertow=True) == before
    assert sorted(p.name for p in Path(vault).iterdir()) == ["Ideas", "Undertow", "sentinel.md"]


def test_no_secrets_in_vault(vault, data_dir, monkeypatch):
    markers = {"SEC_USER_AGENT": "MARKER-UA-7731 marker@example.invalid", "ADMIN_TOKEN": "MARKER-TOKEN-7731",
               "SMTP_PASSWORD": "MARKER-SMTP-7731", "EMAIL_FROM": "marker-from-7731@example.invalid",
               "ANTHROPIC_API_KEY": "MARKER-KEY-7731"}
    for k, v in markers.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        run(vault, data_dir)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    for p in root(vault).rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            for v in markers.values():
                assert v.encode() not in data, (p, v)
            assert b"contact@example.com" not in data


def test_package_never_deletes():
    pattern = re.compile(r"\b(unlink|rmtree|rmdir|removedirs|os\.remove|shutil)\b")
    for p in PACKAGE.rglob("*.py"):
        assert not pattern.search(p.read_text()), p


def test_paths_are_confined(tmp_path):
    v = fs.VaultFS(str(tmp_path / "v"))
    v.ensure_root()
    with pytest.raises(fs.UnsafePath):
        v.path("..", "x.md")
    p = v.path("Tickers", "../../../etc/passwd.md")
    assert Path(p).parent == Path(v.root).resolve() / "Tickers" and Path(p).name == "etc-passwd.md"
    assert fs.sanitize("..") == "untitled" and fs.sanitize(".hidden") == "hidden"
    assert len(fs.sanitize("A" * 500)) == fs.MAX_COMPONENT


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_symlinked_folder_is_refused(vault, data_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    u = root(vault)
    u.mkdir()
    try:
        os.symlink(outside, u / "Tickers", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    res = run(vault, data_dir)
    assert list(outside.iterdir()) == []
    assert res.errors >= 1  # the ticker notes fail; everything else is still written
    assert (u / "Signals" / f"{SIGNAL_STEM}.md").exists()


def test_one_bad_note_does_not_stop_the_export(vault, data_dir, monkeypatch):
    real = exporter._signal_note

    def flaky(ctx, a):
        if a.form == "424B4":
            raise RuntimeError("boom")
        return real(ctx, a)

    monkeypatch.setattr(exporter, "_signal_note", flaky)
    res = run(vault, data_dir, evidence_fn=lambda *_: 1 / 0, paper_fn=lambda: 1 / 0)
    assert res.errors == 1
    assert (root(vault) / "Signals" / f"{SIGNAL_STEM}.md").exists()
    assert (root(vault) / "Tickers" / "MICR.md").exists()
    assert "errors=1" in (root(vault) / "log.md").read_text()


def test_export_result_shape(vault, data_dir):
    res = run(vault, data_dir)
    d = res.to_dict()
    assert set(d) == {"created", "updated", "unchanged", "conflicts", "errors", "counts", "conflict_paths", "started_at", "finished_at"}
    assert isinstance(res, ExportResult) and d["finished_at"].endswith("Z")
    assert read_state(data_dir)["last_export"] == json.loads(json.dumps(d))
    assert read_state(str(Path(data_dir) / "missing")) is None
    assert count_conflicts(str(Path(vault) / "nope")) == 0


# --- frontmatter -------------------------------------------------------------------------------------------------


def test_frontmatter_emitter_round_trips():
    fields = [("type", "x"), ("ticker", "[[ABCD]]"), ("n", 3), ("f", 1e-05), ("big", 12345678.5), ("ok", True),
              ("none", None), ("d", date(2026, 10, 21)), ("ts", utc(2026, 10, 21, 1, 2, 3)), ("lst", ["a", "b: c"]),
              ("empty", []), ("quote", 'he said "hi"\nnext')]
    text = frontmatter.emit(fields)
    assert text == frontmatter.emit(fields)  # deterministic
    assert '"[[ABCD]]"' in text
    meta = yaml.safe_load(text.split("---\n")[1])
    assert meta["ticker"] == "[[ABCD]]" and meta["f"] == pytest.approx(1e-05) and meta["big"] == 12345678.5
    assert meta["d"] == date(2026, 10, 21) and meta["ts"] == utc(2026, 10, 21, 1, 2, 3)
    assert meta["lst"] == ["a", "b: c"] and meta["empty"] == [] and meta["quote"] == 'he said "hi"\nnext'
    assert [k for k, _ in frontmatter.chunks(text.split("---\n")[1])] == [k for k, _ in fields]


def test_fallback_parser_handles_simple_forms():
    text = 'type: thesis\nticker: "[[ABCD]]"\ntags: [undertow/thesis, idea]\nother:\n  - a\n  - "b"\nn: 3\nd: 2026-10-21\n'
    meta = frontmatter._mini_parse(text)
    assert meta == {"type": "thesis", "ticker": "[[ABCD]]", "tags": ["undertow/thesis", "idea"], "other": ["a", "b"],
                    "n": 3, "d": date(2026, 10, 21)}
    with pytest.raises(frontmatter.FrontmatterError):
        frontmatter._mini_parse("- orphan\n")


def test_read_theses_without_pyyaml(tmp_path, monkeypatch):
    monkeypatch.setattr(frontmatter, "_yaml", None)  # the package must work when PyYAML is missing
    v = tmp_path / "vault"
    _note(v, "a.md", '---\ntags: [undertow/thesis]\nticker: "[[ABCD]]"\nupdated: 2026-10-20\n---\n# A\n')
    _note(v, "b.md", "---\ntype: thesis\nticker: ABCD\nbroken line without colon\n---\nb\n")
    res = read_theses(str(v), ticker="abcd")
    assert [(t["path"], t["title"], t["updated"]) for t in res] == [("a.md", "A", "2026-10-20")]


# --- thesis read-back --------------------------------------------------------------------------------------------


def _note(base: Path, rel: str, text: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_read_theses(tmp_path):
    v = tmp_path / "vault"
    _note(v, "Theses/tiny.md", '---\ntype: thesis\nticker: "[[TINY]]"\nupdated: 2026-10-20\n---\n# Tiny runway\n\n' + "body " * 300)
    _note(v, "Theses/tag-string.md", "---\ntags: \"#undertow/thesis\"\nticker: micr\ndate: 2026-10-18\ntitle: Micro view\n---\ntext\n")
    _note(v, "deep/a/b/tag-list.md", "---\ntags:\n  - idea\n  - undertow/thesis\nticker: [TINY, MICR]\nupdated: 2026-10-19\n---\nlist\n")
    _note(v, "Undertow/Tickers/TINY.md", "---\ntype: thesis\nticker: TINY\n---\nmachine\n")
    _note(v, ".obsidian/x.md", "---\ntype: thesis\nticker: TINY\n---\nconfig\n")
    _note(v, ".trash/y.md", "---\ntype: thesis\nticker: TINY\n---\ntrash\n")
    _note(v, "Theses/bad.md", "---\ntype: thesis\nticker: [unclosed\n---\nbad\n")
    _note(v, "Theses/plain.md", "---\ntype: idea\nticker: TINY\n---\nnot a thesis\n")
    _note(v, "Theses/no-fm.md", "# just text\n")
    _note(v, "Theses/note.txt", "---\ntype: thesis\n---\n")
    _note(v, "Theses/nested/Undertow/kept.md", "---\ntype: thesis\nticker: ZZZ\nupdated: 2026-10-01\n---\nnested\n")
    _note(v, "Theses/exec.md", "---\ntype: thesis\nticker: !!python/object/apply:os.system [\"echo pwned\"]\n---\nx\n")

    allt = read_theses(str(v))
    paths = [t["path"] for t in allt]
    assert paths == ["Theses/tiny.md", "deep/a/b/tag-list.md", "Theses/tag-string.md", "Theses/nested/Undertow/kept.md"]
    first = allt[0]
    assert first["title"] == "Tiny runway" and first["ticker"] == "TINY" and first["updated"] == "2026-10-20"
    assert len(first["excerpt"]) <= 601 and "  " not in first["excerpt"]
    assert allt[2]["title"] == "Micro view" and allt[2]["tags"] == ["undertow/thesis"] and allt[2]["ticker"] == "MICR"

    tiny = read_theses(str(v), ticker="tiny")
    assert [t["path"] for t in tiny] == ["Theses/tiny.md", "deep/a/b/tag-list.md"]
    assert all(t["ticker"] == "TINY" for t in tiny)
    assert [t["path"] for t in read_theses(str(v), ticker="[[MICR]]")] == ["deep/a/b/tag-list.md", "Theses/tag-string.md"]
    assert len(read_theses(str(v), limit=1)) == 1
    assert read_theses(str(tmp_path / "missing")) == []


def test_read_theses_mtime_fallback_and_size_cap(tmp_path, monkeypatch):
    from app.vault import readback

    v = tmp_path / "vault"
    _note(v, "t.md", "---\ntype: thesis\nticker: TINY\n---\nno date\n")
    _note(v, "big.md", "---\ntype: thesis\nticker: TINY\n---\n" + "x" * 2000)
    monkeypatch.setattr(readback, "MAX_BYTES", 1000)
    res = read_theses(str(v))
    assert [t["path"] for t in res] == ["t.md"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", res[0]["updated"]) and res[0]["title"] == "t"


# --- working paper copy ------------------------------------------------------------------------------------------

REPO = find_repo_root()


@pytest.mark.skipif(not (REPO / "docs").is_dir(), reason=f"repo docs/ not available at {REPO}; mount the repo at /repo")
def test_working_paper_copy_is_identical():
    # Byte equality up to the checkout's line endings (git may check out CRLF on Windows), as in test_paper_numbers.
    def norm(p: Path) -> bytes:
        return p.read_bytes().replace(b"\r\n", b"\n")

    assert norm(PACKAGE / "working_paper.md") == norm(REPO / PAPER), f"copy {PAPER} to backend/app/vault/working_paper.md"
