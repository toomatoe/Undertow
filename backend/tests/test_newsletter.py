import json
import logging
import re
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import Base, SessionLocal, engine
from app.fundamentals import service as fundamentals
from app.models import Article, ArticleTicker, Company, JournalEntry, TradingHalt
from app.newsletter import service as nl

WEEK_END = date(2026, 10, 11)  # Sunday; ISO week 2026-W41 (Oct 5..11)
BANNED = re.compile(r"\b(buy\w*|sell\w*|short it|target\w*|opportunit\w*|guarantee\w*|profit\w*)\b", re.I)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


_n = 0
CALLS: list[int] = []


def filing(sym, form, signals, severity, when, title=None):
    global _n
    _n += 1
    a = Article(url=f"https://www.sec.gov/Archives/{_n}", url_hash=f"h{_n}", title_hash=f"t{_n}", title=title or f"{form}: {sym} Corp",
                source="edgar", source_name="SEC EDGAR", published_at=when, form=form, signals=signals, severity=severity)
    a.tickers = [ArticleTicker(symbol=sym, method="edgar")]
    return a


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    (tmp_path / "backtests").mkdir()
    (tmp_path / "event_study.json").write_text(json.dumps({"results": [
        {"signal": "delisting_notice", "bucket": "nano", "horizon_days": 20, "n": 140, "mean_abnormal": -0.081, "median_abnormal": -0.06,
         "excess_vs_baseline": -0.05, "t_stat": -4.2, "significant": True},
        {"signal": "delisting_notice", "bucket": "nano", "horizon_days": 5, "n": 140, "mean_abnormal": -0.03, "t_stat": -2.0, "significant": False},
        {"signal": "offering_priced", "bucket": "nano", "horizon_days": 20, "n": 300, "mean_abnormal": -0.12, "median_abnormal": -0.1,
         "excess_vs_baseline": None, "t_stat": -6.0, "significant": True},
    ]}))
    (tmp_path / "backtests" / "report_latest.json").write_text(json.dumps({
        "generated_at": "2026-10-16T17:38:28+00:00", "strategy": {"name": "Offering drift test"},
        "key_finding": {"text": "The drift is real before frictions. This is a great opportunity. With every assumed friction the strategy loses money, so it is not tradable as specified."},
    }))
    CALLS.clear()

    def fake_profile(cik, data_dir, user_agent, symbol=None):
        CALLS.append(cik)
        if cik == 2:
            return {"cash": {"value": 1e6, "as_of": "2026-06-30"}, "runway": {"status": "burning", "months": 3.2, "runs_out_around": "2026-10-05"}}
        return {"cash": None, "runway": {"status": "unknown"}}

    monkeypatch.setattr(fundamentals, "company_profile", fake_profile)
    return tmp_path


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([
            Company(symbol="TINY", cik=1, name="Tiny Therapeutics", size_bucket="nano", public_float=20_000_000),
            Company(symbol="MICR", cik=2, name="Micro Devices Co", size_bucket="nano", public_float=35_000_000),
            Company(symbol="DIL", cik=4, name="Diluto Inc", size_bucket="micro", public_float=120_000_000),
            Company(symbol="BIG", cik=3, name="Big Corp", size_bucket="large", public_float=50_000_000_000),
        ])
        s.add_all([
            filing("TINY", "8-K", ["delisting_notice", "officer_change"], 3, utc(2026, 10, 6, 14)),
            filing("MICR", "424B4", ["offering_priced"], 2, utc(2026, 10, 7, 21, 5)),
            filing("DIL", "S-3", ["shelf_registered"], 1, utc(2026, 10, 8, 13)),
            filing("DIL", "8-K", ["unregistered_equity"], 2, utc(2026, 10, 9, 20)),
            filing("BIG", "8-K", ["bankruptcy"], 3, utc(2026, 10, 7, 12)),  # large cap: excluded
            filing("TINY", "8-K", ["non_reliance"], 3, utc(2026, 10, 13, 14)),  # next week: excluded
            filing("TINY", "8-K", ["auditor_change"], 2, utc(2026, 10, 5, 3)),  # Sunday 23:00 ET Oct 4: previous week
        ])
        news = Article(url="https://news/1", url_hash="n1", title_hash="n1", title="Tiny news", source="rss", source_name="X",
                       published_at=utc(2026, 10, 6, 15))
        news.tickers = [ArticleTicker(symbol="TINY", method="cashtag")]
        s.add(news)
        s.add_all([
            TradingHalt(symbol="TINY", name="Tiny Therapeutics", market="NASDAQ", reason_code="T1", halted_at=utc(2026, 10, 6, 13, 50)),
            TradingHalt(symbol="MICR", name="Micro Devices", market="NASDAQ", reason_code="LUDP", halted_at=utc(2026, 10, 7, 15)),
            TradingHalt(symbol="BIG", name="Big Corp", market="NYSE", reason_code="H10", halted_at=utc(2026, 10, 7, 15)),
            TradingHalt(symbol="OTCX", name="Unknown Co", market="NASDAQ", reason_code="H10", halted_at=utc(2026, 10, 8, 15),
                        resumed_at=utc(2026, 10, 9, 14)),
        ])
        for i in range(6):
            s.add(JournalEntry(article_id=1000 + i, ticker="MICR", signals=["offering_priced"], primary_signal="offering_priced", direction="-",
                               severity=2, size_bucket="nano", filed_at=utc(2026, 8, 3 + i, 14), status="complete", abn_20=-0.05 * (i % 3)))
        s.commit()


def build(data_dir, **kw):
    with SessionLocal() as s:
        return nl.build_issue(s, str(data_dir), WEEK_END, user_agent="test", public_base_url="https://quantdesk.test", **kw)


def test_ids_and_weeks():
    assert nl.issue_id(WEEK_END) == "2026-W41"
    assert nl.last_completed_week_end(date(2026, 10, 12)) == WEEK_END  # Monday -> yesterday
    assert nl.last_completed_week_end(date(2026, 10, 11)) == date(2026, 10, 4)  # Sunday isn't complete yet
    assert nl.last_completed_week_end(date(2026, 10, 16)) == WEEK_END
    assert nl.current_week_end(date(2026, 10, 16)) == date(2026, 10, 18)


def test_sections(data_dir):
    issue = build(data_dir)
    h = issue["headline"]
    assert (issue["id"], issue["week_start"], issue["partial"]) == ("2026-W41", "2026-10-05", False)
    assert issue["coverage_note"] is None  # signal filings exist from before the week
    assert h["signal_filings"] == 4 and h["companies"] == 3
    assert h["by_severity"] == {"3": 1, "2": 2, "1": 1}
    assert h["by_size"] == {"nano": 2, "micro": 2, "small": 0}

    top = issue["top_filings"]
    assert [t["ticker"] for t in top] == ["TINY", "DIL", "MICR"]  # severity 3 first, then 2 newest first
    tiny = top[0]
    assert tiny["company"] == "Tiny Therapeutics" and tiny["size"] == "nano" and tiny["form"] == "8-K"
    assert [s["label"] for s in tiny["signals"]] == ["Delisting notice", "Executive / director change"]
    assert tiny["evidence"]["n"] == 140 and tiny["evidence"]["horizon_days"] == 20
    assert top[1]["evidence"] is None  # no study row for unregistered_equity/micro

    dil = {d["ticker"]: d for d in issue["dilution_watch"]}
    assert set(dil) == {"MICR", "DIL"}
    assert dil["DIL"]["offering_signals"] == 2
    assert dil["MICR"]["runway"]["months"] == 3.2 and "runway under 6 months" in dil["MICR"]["reasons"][0]
    assert issue["runway_lookups"] == 2 and sorted(CALLS) == [2, 4]


def test_stale_runway_does_not_qualify(data_dir, monkeypatch):
    monkeypatch.setattr(fundamentals, "company_profile", lambda *a, **k: {"cash": {"value": 1e5, "as_of": "2023-06-30"},
                        "runway": {"status": "burning", "months": 0.1, "runs_out_around": "2023-07-02"}})
    issue = build(data_dir)
    assert [d["ticker"] for d in issue["dilution_watch"]] == ["DIL"]  # MICR no longer qualifies on a 2023 cash figure
    assert "too old to estimate runway" in nl.render_markdown(issue)

    assert [x["symbol"] for x in issue["serious_halts"]] == ["TINY", "OTCX"]  # LUDP not serious, BIG is large

    tr = issue["track_record"]
    assert tr["recorded"] == 6 and tr["collecting"] is None
    assert tr["rows"][0]["signal"] == "offering_priced" and tr["rows"][0]["n_20"] == 6 and tr["rows"][0]["expected_20"] == -0.12

    note = issue["research_note"]
    assert "opportunity" not in note["text"] and note["text"].startswith("The drift is real")

    md = nl.render_markdown(issue)
    for heading in ("Top filings this week", "Dilution watch", "Serious trading halts", "Track record update", "Research note"):
        assert f"## {heading}" in md
    assert "https://quantdesk.test/ticker/TINY" in md and "https://quantdesk.test/methodology" in md
    assert "Historical, hypothetical" in md and "48 hours" in md


def test_still_collecting_and_missing_report(data_dir):
    (data_dir / "backtests" / "report_latest.json").unlink()
    with SessionLocal() as s:
        s.query(JournalEntry).delete()
        s.add(JournalEntry(article_id=2000, ticker="TINY", signals=["delisting_notice"], primary_signal="delisting_notice", direction="-",
                           severity=3, size_bucket="nano", filed_at=utc(2026, 10, 6, 14), status="open"))
        s.commit()
    issue = build(data_dir)
    assert issue["research_note"] is None
    assert issue["track_record"]["collecting"] == {"recorded": 1, "first_due": "2026-11-04"}
    md = nl.render_markdown(issue)
    assert "Still collecting: 1 signals recorded, first 20-day results due ~Nov 4, 2026" in md
    assert "## Research note" not in md


def test_no_banned_words_and_email_safe_html(data_dir):
    issue = build(data_dir)
    for text in (nl.render_markdown(issue), nl.render_html(issue)):
        assert not BANNED.findall(text), BANNED.findall(text)
        assert nl.banned_words(text) == []
    page = nl.render_html(issue).lower()
    for tag in ("<script", "<link", "<style", "class="):
        assert tag not in page
    assert "max-width:640px" in page and "<table" in page
    assert nl.banned_words("Buy now, a real Opportunity, short it") == ["buy", "opportunity", "short it"]
    assert nl.banned_words("Stays profitable; selling, buying, targets, opportunities, guaranteed profits") == [
        "buying", "guaranteed", "opportunities", "profitable", "profits", "selling", "targets"]


def test_research_note_drops_inflected_banned_words(data_dir):
    (data_dir / "backtests" / "report_latest.json").write_text(json.dumps({
        "generated_at": "2026-10-16T17:38:28+00:00", "strategy": {"name": "Offering drift test"},
        "key_finding": {"text": "The drift is real before frictions. It stays profitable at every borrow fee tested (out-of-sample). "
                                "Insiders kept selling into the drift. Results are historical and hypothetical."},
    }))
    note = build(data_dir)["research_note"]
    assert note["text"] == "The drift is real before frictions. Results are historical and hypothetical."
    assert nl.banned_words(note["text"]) == []


def test_immutable_unless_forced(data_dir):
    with SessionLocal() as s:
        first, created = nl.generate(s, str(data_dir), WEEK_END, public_base_url="https://quantdesk.test")
        assert created
        for ext in ("json", "md", "html"):
            assert (data_dir / "newsletters" / f"2026-W41.{ext}").exists()
        s.add(filing("TINY", "8-K", ["bankruptcy"], 3, utc(2026, 10, 9, 14)))
        s.commit()
        again, created = nl.generate(s, str(data_dir), WEEK_END)
        assert not created and again == first and again["headline"]["signal_filings"] == 4
        assert nl.ensure_latest(s, str(data_dir), today=date(2026, 10, 14)) is None  # exists already
        forced, created = nl.generate(s, str(data_dir), WEEK_END, force=True)
        assert created and forced["headline"]["signal_filings"] == 5


def test_ensure_latest_builds_last_completed_week(data_dir):
    with SessionLocal() as s:
        assert nl.ensure_latest(s, str(data_dir), today=date(2026, 10, 12)) == "2026-W41"
    assert [i["id"] for i in nl.list_issues(str(data_dir))] == ["2026-W41"]


def test_preview_is_partial_and_unsaved(data_dir):
    with SessionLocal() as s:
        issue = nl.preview(s, str(data_dir), now=utc(2026, 10, 14, 12))
    assert issue["id"] == "2026-W42" and issue["partial"] and issue["headline"]["signal_filings"] == 1  # TINY non_reliance
    assert not (data_dir / "newsletters").exists()


def test_coverage_note_when_collection_started_later(data_dir):
    with SessionLocal() as s:
        s.query(ArticleTicker).delete()
        s.query(Article).delete()
        s.commit()
    issue = build(data_dir)
    assert issue["headline"]["signal_filings"] == 0
    assert "has not started" in issue["coverage_note"]
    with SessionLocal() as s:
        s.add(filing("TINY", "8-K", ["delisting_notice"], 3, utc(2026, 10, 9, 14)))
        s.commit()
    issue = build(data_dir)
    assert issue["coverage_note"] == "Live filing collection began Oct 9, 2026, so this week is only partly covered."
    assert issue["coverage_note"] in nl.render_markdown(issue)


def test_api(data_dir, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(data_dir))
    with SessionLocal() as s:
        nl.generate(s, str(data_dir), WEEK_END, public_base_url="https://quantdesk.test")
    client = TestClient(main.app)
    issues = client.get("/api/newsletter/issues").json()
    assert issues[0]["id"] == "2026-W41" and issues[0]["headline"]["signal_filings"] == 4 and issues[0]["week_end"] == "2026-10-11"
    one = client.get("/api/newsletter/2026-W41").json()
    assert one["markdown"].startswith("# Small-Cap Filing Radar") and one["top_filings"][0]["ticker"] == "TINY"
    page = client.get("/api/newsletter/2026-W41.html")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html") and "<table" in page.text
    assert client.get("/api/newsletter/2026-W01").status_code == 404
    assert client.get("/api/newsletter/..%2Fsecrets").status_code == 404
    prev = client.post("/api/newsletter/preview").json()
    assert prev["partial"] is True and "markdown" in prev and "html" in prev
    assert [i["id"] for i in client.get("/api/newsletter/issues").json()] == ["2026-W41"]  # preview not saved


def test_banned_pattern_matches_service():
    assert BANNED.pattern == nl.BANNED.pattern and BANNED.flags == nl.BANNED.flags


def test_missing_form_falls_back_to_filing(data_dir):
    with SessionLocal() as s:
        a = filing("MICR", None, ["offering_priced"], 2, utc(2026, 10, 8, 15), title="Micro Devices Co")
        s.add(a)
        s.commit()
    issue = build(data_dir)
    micr = {d["ticker"]: d for d in issue["dilution_watch"]}["MICR"]
    assert None in [f["form"] for f in micr["filings"]]
    md, page = nl.render_markdown(issue), nl.render_html(issue)
    assert "None" not in md and "None" not in page
    assert "[filing](https://www.sec.gov/Archives/" in md
    assert "Form n/a" in md  # top-filings line for the formless filing


def test_flagged_words_ignore_names_but_catch_our_prose(data_dir, caplog, monkeypatch):
    with SessionLocal() as s:
        s.add(Company(symbol="SLS", cik=5, name="Sellas Profit Targets Inc", size_bucket="micro", public_float=90_000_000))
        s.add(filing("SLS", "8-K", ["delisting_notice"], 3, utc(2026, 10, 8, 14), title="8-K: Sellas Profit Targets Inc"))
        s.add(TradingHalt(symbol="BUYZ", name="Buyz Opportunity Fund", market="NASDAQ", reason_code="T1", halted_at=utc(2026, 10, 8, 16)))
        s.commit()
    with caplog.at_level(logging.ERROR, logger=nl.log.name):
        issue = build(data_dir)
    assert "Sellas" in nl.render_markdown(issue) and "Buyz" in nl.render_html(issue)
    assert issue["flagged_words"] == []
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    issue["sources_note"] = "Our best buying opportunity."  # our own prose: flagged in both renderers
    assert nl.flagged_words(issue) == ["buying", "opportunity"]

    caplog.clear()
    monkeypatch.setattr(nl, "SOURCES_NOTE", "Selling pressure is guaranteed.")
    with caplog.at_level(logging.ERROR, logger=nl.log.name):
        flagged = build(data_dir)
    assert flagged["flagged_words"] == ["guaranteed", "selling"]
    assert any(r.levelno == logging.ERROR and "flagged words" in r.getMessage() for r in caplog.records)


def test_flagged_words_saved_with_issue(data_dir):
    with SessionLocal() as s:
        issue, _ = nl.generate(s, str(data_dir), WEEK_END, public_base_url="https://quantdesk.test")
    assert issue["flagged_words"] == [] and nl.load_issue(str(data_dir), "2026-W41")["flagged_words"] == []


def test_research_note_logs_dropped_sentence_count(data_dir, caplog):
    with caplog.at_level(logging.INFO, logger=nl.log.name):
        build(data_dir)
    assert any("dropped 1 sentence" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records)
