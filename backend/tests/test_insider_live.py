"""Live Form 4 forward test (app.insiders.live): fixture XML + canned getcurrent Atom feeds, no network."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import Base, SessionLocal, engine
from app.insiders import datasets, evidence, live, study
from app.insiders.form4 import UnsafeXMLError, parse_ownership_xml
from app.journal import digest
from app.journal import service as journal
from app.models import AlertLog, Article, Company, JournalEntry
from app.pipeline import ingest
from app.pipeline.signals import ALL_SIGNALS, FORWARD_TEST_SIGNALS, signal_def
from app.pipeline.tickers import TickerUniverse

FIX = Path(__file__).parent / "fixtures" / "form4_live"
UA = "afterfile-test agent"
MICRO_CIK, BIG_CIK = 111111, 222222
DOCS_ROW = "docs/results/event_study_insider_purchases_2026-10-19.json"

# accession -> (issuer cik, fixture). One accession per filing, as on EDGAR.
FILINGS = {
    "0000900001-26-000001": (MICRO_CIK, "director_purchase.xml"),        # $20,000, insider 900001
    "0000900002-26-000001": (MICRO_CIK, "officer_purchase.xml"),         # $20,000, insider 900002
    "0000900003-26-000001": (MICRO_CIK, "director_small_purchase.xml"),  # $3,000, insider 900003
    "0000900004-26-000001": (MICRO_CIK, "officer_small_purchase.xml"),   # $3,000, insider 900004
    "0000900005-26-000001": (MICRO_CIK, "plan_10b5_1_purchase.xml"),
    "0000900006-26-000001": (MICRO_CIK, "sale_code_s.xml"),
    "0000900007-26-000001": (MICRO_CIK, "ten_percent_only.xml"),
    "0000900008-26-000001": (BIG_CIK, "bigco_purchase.xml"),
    "0000900009-26-000001": (MICRO_CIK, "doctype.xml"),
}
A, B, C_SMALL, D_SMALL, PLAN, SALE, TENPCT, BIG, DOCTYPE = FILINGS


def entry_xml(acc: str, filed: date, hour: int = 16) -> str:
    cik, _ = FILINGS[acc]
    company = "Microtest Example Corp" if cik == MICRO_CIK else "Bigtest Example Corp"
    nod = acc.replace("-", "")
    upd = f"{filed.isoformat()}T{hour:02d}:05:00-04:00"
    return f"""<entry>
<title>4 - {company} ({cik:010d}) (Issuer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/{cik}/{nod}/{acc}-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; {filed.isoformat()} &lt;b&gt;AccNo:&lt;/b&gt; {acc} &lt;b&gt;Size:&lt;/b&gt; 5 KB</summary>
<updated>{upd}</updated>
<category scheme="https://www.sec.gov/" label="form type" term="4"/>
<id>urn:tag:sec.gov,2008:accession-number={acc}</id>
</entry>
<entry>
<title>4 - Example Owner (0000{acc[4:10]}) (Reporting)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/{cik}/{nod}/{acc}-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; {filed.isoformat()} &lt;b&gt;AccNo:&lt;/b&gt; {acc}</summary>
<updated>{upd}</updated>
<id>urn:tag:sec.gov,2008:accession-number={acc}</id>
</entry>"""


def feed(*items: tuple[str, date]) -> bytes:
    body = "\n".join(entry_xml(acc, d) for acc, d in items)
    return (f'<?xml version="1.0" encoding="ISO-8859-1" ?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n'
            f"<title>Latest Filings</title>\n<updated>2026-10-14T16:30:00-04:00</updated>\n{body}\n</feed>\n").encode()


class FakeSEC:
    """Routes getcurrent, index.json and the raw XML to fixtures; records every URL."""

    def __init__(self, feed_bytes: bytes):
        self.feed = feed_bytes
        self.calls: list[str] = []
        self.by_folder = {acc.replace("-", ""): (acc, fix) for acc, (_, fix) in FILINGS.items()}

    def __call__(self, url, params=None, headers=None, timeout=None):
        assert headers and headers["User-Agent"] == UA  # from settings, never hard-coded
        self.calls.append(url)
        req = httpx.Request("GET", url)
        if url == live.FEED_URL:
            assert params["type"] == "4" and params["output"] == "atom"
            return httpx.Response(200, content=self.feed, request=req)
        folder = url.split("/")[-2]
        if folder not in self.by_folder:
            return httpx.Response(404, request=req)
        acc, fix = self.by_folder[folder]
        if url.endswith("/index.json"):
            items = [{"name": f"{acc}.txt"}, {"name": f"{acc}-index.htm"}, {"name": "form4.xml"}]
            return httpx.Response(200, json={"directory": {"item": items}}, request=req)
        if url.endswith("/form4.xml"):
            return httpx.Response(200, content=(FIX / fix).read_bytes(), request=req)
        return httpx.Response(404, request=req)

    def xml_calls(self) -> list[str]:
        return [u for u in self.calls if u != live.FEED_URL]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([
            Company(symbol="MTEX", cik=MICRO_CIK, name="Microtest Example Corp", public_float=120_000_000, size_bucket="micro"),
            Company(symbol="BGEX", cik=BIG_CIK, name="Bigtest Example Corp", public_float=900_000_000, size_bucket="small"),
        ])
        s.commit()
    monkeypatch.setattr(datasets, "throttle", lambda: None)
    monkeypatch.delenv("INSIDER_LIVE_ENABLED", raising=False)
    hooks: list[int] = []
    monkeypatch.setattr(ingest, "NEW_ARTICLE_HOOKS", [hooks.append])
    return hooks


def settings(tmp_path, **kw):
    return SimpleNamespace(edgar_enabled=True, sec_user_agent=UA, data_dir=str(tmp_path), **kw)


def poll(tmp_path, items, now_day: date, sec: FakeSEC | None = None) -> tuple[dict, FakeSEC]:
    sec = sec or FakeSEC(feed(*items))
    now = datetime(now_day.year, now_day.month, now_day.day, 21, 0, tzinfo=timezone.utc)
    stats = live.poll_form4(settings(tmp_path), TickerUniverse(), SessionLocal, http_get=sec, now=now)
    return stats, sec


def articles() -> list[Article]:
    with SessionLocal() as s:
        return list(s.query(Article).order_by(Article.id).all())


def purchases(tmp_path) -> list[dict]:
    return live.load_purchases(str(tmp_path))


# --- feed and qualification --------------------------------------------------------


def test_parse_canned_feed_keeps_issuer_side_form4_only():
    entries = live.parse_feed((FIX / "getcurrent_form4.atom").read_bytes())
    assert [(e.accession, e.issuer_cik) for e in entries] == [(A, MICRO_CIK), (BIG, BIG_CIK)]  # 4/A and Reporting dropped
    assert entries[0].filing_date == date(2026, 10, 14)
    assert entries[0].accepted_at == datetime(2026, 10, 14, 20, 5, 12, tzinfo=timezone.utc)


def test_canned_feed_cycle_skips_non_micro_without_fetching(tmp_path, _env):
    sec = FakeSEC((FIX / "getcurrent_form4.atom").read_bytes())
    stats, _ = poll(tmp_path, [], date(2026, 10, 14), sec)
    assert stats["not_micro"] == 1 and stats["xml_fetched"] == 1 and stats["qualifying_filings"] == 1
    assert not any(f"/{BIG_CIK}/" in u for u in sec.calls)
    assert [(p["accession"], p["insider_cik"], p["value"], p["ticker"]) for p in purchases(tmp_path)] == [(A, 900001, 20000.0, "MTEX")]
    assert articles() == [] and _env == []  # a single insider never emits


def test_shared_rules_on_fixtures():
    def q(fix):
        parsed = parse_ownership_xml((FIX / fix).read_bytes())
        return live.qualifying_purchases(parsed, "acc", date(2026, 10, 14))

    [p] = q("director_purchase.xml")
    assert (p.issuer_cik, p.insider_cik, p.value) == (MICRO_CIK, 900001, 20000.0)
    assert q("plan_10b5_1_purchase.xml") == []  # 10b5-1
    assert q("sale_code_s.xml") == []  # code S
    assert q("ten_percent_only.xml") == []  # 10% owner only
    rows = live.rows_from_xml(parse_ownership_xml((FIX / "ten_percent_only.xml").read_bytes()), "acc", date(2026, 10, 14))
    assert study.exclusion_reason(rows[0]) == "not_director_or_officer"  # the study's own predicate decides


def test_doctype_rejected_safely_and_not_refetched(tmp_path):
    with pytest.raises(UnsafeXMLError):
        parse_ownership_xml((FIX / "doctype.xml").read_bytes())
    stats, sec = poll(tmp_path, [(DOCTYPE, date(2026, 10, 14))], date(2026, 10, 14))
    assert stats["unsafe_xml"] == 1 and purchases(tmp_path) == []
    stats, sec2 = poll(tmp_path, [(DOCTYPE, date(2026, 10, 14))], date(2026, 10, 14))
    assert stats["already_seen"] == 1 and sec2.xml_calls() == []


# --- cluster rule -----------------------------------------------------------------


def test_single_purchase_then_second_insider_emits_exactly_once(tmp_path, _env):
    d1, d2 = date(2026, 10, 5), date(2026, 10, 12)
    poll(tmp_path, [(A, d1)], d1)
    assert articles() == []
    stats, _ = poll(tmp_path, [(A, d1), (B, d2)], d2)
    assert stats["emitted"] == 1 and stats["already_seen"] == 1
    [a] = articles()
    assert a.title == "Insider cluster purchase: MTEX (2 insiders, $20,000 total)"
    assert (a.source, a.form, a.signals, a.severity, a.cik) == ("edgar", "4", ["insider_cluster_purchase"], 2, MICRO_CIK)
    assert a.url == f"https://www.sec.gov/Archives/edgar/data/{MICRO_CIK}/{B.replace('-', '')}/{B}-index.htm"
    assert [t.symbol for t in a.tickers] == ["MTEX"] and a.body == ""
    assert "hypothetical" in a.snippet
    assert _env == [a.id]  # NEW_ARTICLE_HOOKS fired once
    stats, _ = poll(tmp_path, [(A, d1), (B, d2)], d2)  # same feed again: nothing new
    assert stats["emitted"] == 0 and len(articles()) == 1 and _env == [a.id]


def test_purchase_eleven_days_later_does_not_cluster(tmp_path):
    poll(tmp_path, [(A, date(2026, 10, 1))], date(2026, 10, 1))
    stats, _ = poll(tmp_path, [(B, date(2026, 10, 12))], date(2026, 10, 12))
    assert stats["emitted"] == 0 and articles() == []


def test_ten_days_is_inside_the_window(tmp_path):
    poll(tmp_path, [(A, date(2026, 10, 2))], date(2026, 10, 2))
    stats, _ = poll(tmp_path, [(B, date(2026, 10, 12))], date(2026, 10, 12))
    assert stats["emitted"] == 1


def test_small_purchases_count_toward_cluster_but_not_toward_min_value(tmp_path):
    poll(tmp_path, [(C_SMALL, date(2026, 10, 5))], date(2026, 10, 5))
    stats, _ = poll(tmp_path, [(D_SMALL, date(2026, 10, 6))], date(2026, 10, 6))
    assert stats["emitted"] == 0  # 2 insiders, but $3,000 issuer-day < MIN_VALUE
    stats, _ = poll(tmp_path, [(A, date(2026, 10, 8))], date(2026, 10, 8))
    assert stats["emitted"] == 1  # A alone would not cluster; the two small buyers make it one
    [a] = articles()
    assert a.title == "Insider cluster purchase: MTEX (3 insiders, $20,000 total)"


def test_excluded_filings_never_count(tmp_path):
    d = date(2026, 10, 6)
    stats, _ = poll(tmp_path, [(PLAN, d), (SALE, d), (TENPCT, d), (BIG, d), (A, d)], d)
    assert stats["not_qualifying"] == 3 and stats["not_micro"] == 1 and stats["emitted"] == 0
    assert [p["accession"] for p in purchases(tmp_path)] == [A]


def test_seen_set_persisted_prevents_refetch(tmp_path):
    d = date(2026, 10, 6)
    _, sec = poll(tmp_path, [(A, d)], d)
    assert len(sec.xml_calls()) == 2  # index.json + XML
    assert A in json.loads((tmp_path / live.SEEN_FILE).read_text())["seen"]
    _, sec2 = poll(tmp_path, [(A, d)], d)
    assert sec2.xml_calls() == [] and len(purchases(tmp_path)) == 1


def test_per_cycle_xml_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "MAX_XML_PER_CYCLE", 1)
    d = date(2026, 10, 6)
    stats, _ = poll(tmp_path, [(A, d), (B, d)], d)
    assert stats["xml_fetched"] == 1 and stats["capped"] == 1 and stats["emitted"] == 0
    stats, _ = poll(tmp_path, [(A, d), (B, d)], d)
    assert stats["xml_fetched"] == 1 and stats["emitted"] == 1


def test_transient_fetch_error_is_retried(tmp_path):
    d = date(2026, 10, 6)

    class Flaky(FakeSEC):
        def __call__(self, url, **kw):
            if url.endswith("/index.json"):
                raise httpx.ConnectError("down")
            return super().__call__(url, **kw)

    stats, _ = poll(tmp_path, [(A, d)], d, Flaky(feed((A, d))))
    assert stats["fetch_errors"] == 1
    stats, _ = poll(tmp_path, [(A, d)], d)
    assert stats["qualifying_filings"] == 1


def test_gates(tmp_path, monkeypatch):
    sec = FakeSEC(feed((A, date(2026, 10, 6))))
    off = SimpleNamespace(edgar_enabled=False, sec_user_agent=UA, data_dir=str(tmp_path))
    assert live.poll_form4(off, TickerUniverse(), SessionLocal, http_get=sec) == {"status": "disabled"}
    monkeypatch.setenv("INSIDER_LIVE_ENABLED", "false")
    assert live.poll_form4(settings(tmp_path), TickerUniverse(), SessionLocal, http_get=sec) == {"status": "disabled"}
    assert sec.calls == []


def test_form4_failure_never_breaks_the_8k_poll(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("form 4 broke")

    monkeypatch.setattr(live, "poll_form4", boom)
    assert ingest._poll_form4(SimpleNamespace(), TickerUniverse()) == {"error": "RuntimeError: form 4 broke"}


# --- taxonomy, evidence, journal --------------------------------------------------


def test_main_taxonomy_untouched_and_forward_signal_resolvable():
    assert not any(code.startswith("insider") for code in ALL_SIGNALS)
    sig = signal_def("insider_cluster_purchase")
    assert sig is FORWARD_TEST_SIGNALS["insider_cluster_purchase"] and sig.direction == "+"
    assert "forward test of pre-registered finding" in sig.label
    assert live.SIGNAL == study.CLUSTER


def test_bundled_row_matches_docs_results():
    bundled = evidence.bundled_row()
    assert (bundled["signal"], bundled["bucket"], bundled["horizon_days"]) == ("insider_cluster_purchase", "micro", 5)
    for base in (Path("/repo"), Path(__file__).resolve().parents[2]):
        if (base / DOCS_ROW).exists():
            docs = json.loads((base / DOCS_ROW).read_text(encoding="utf-8"))
            row = next(r for r in docs["results"] if r["signal"] == "insider_cluster_purchase"
                       and r["bucket"] == "micro" and r["horizon_days"] == 5)
            assert bundled == row
            return
    pytest.skip("docs/results not mounted")


def _insider_article(published: datetime) -> int:
    raw = live.to_raw_article(
        live.ClusterEvent(MICRO_CIK, published.date(), 2, 40_000.0, (A, B)), "MTEX", "Microtest Example Corp", published)
    [aid] = ingest.store_and_publish([raw], TickerUniverse(), body="")
    return aid


def test_to_out_uses_bundled_insider_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))  # no DATA_DIR study -> bundled row
    monkeypatch.setattr(main.state, "forward_evidence", None)
    monkeypatch.setattr(main.state, "sizes", {"MTEX": "micro"})
    aid = _insider_article(datetime.now(timezone.utc))
    with SessionLocal() as s:
        out = main.to_out(s.get(Article, aid))
    assert out.forward_test is True and out.signals[0].forward_test is True
    [ev] = out.evidence
    assert (ev.study, ev.forward_test, ev.horizon_days, ev.bucket, ev.n) == ("insider_purchases", True, 5, "micro", 662)
    assert (ev.excess_vs_baseline, ev.t_stat_clustered, ev.mean_net, ev.companies) == (0.01662, 3.29, 0.00109, 177)


def test_data_dir_study_wins_over_bundled_row(tmp_path, monkeypatch):
    row = {**evidence.bundled_row(), "n": 700}
    (tmp_path / study.INSIDER_RESULTS_FILE).write_text(json.dumps({"results": [row]}))
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(main.state, "forward_evidence", None)
    assert main.forward_evidence()[("insider_cluster_purchase", "micro")].n == 700


def test_journal_long_row_horizon_5_label_and_seal_verifies(tmp_path, monkeypatch):
    aid = _insider_article(datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc))
    with SessionLocal() as s:
        assert journal.record_new(s, str(tmp_path)) == 1
        e = s.query(JournalEntry).one()
        assert (e.article_id, e.primary_signal, e.direction, e.size_bucket) == (aid, "insider_cluster_purchase", "+", "micro")
        assert journal.evaluation_horizon(e.primary_signal) == 5 and journal.evaluation_horizon("auditor_change") == 20
        assert journal.forward_test_label(e.primary_signal) == "forward test of pre-registered finding"
        e.created_at = datetime(2026, 10, 13, 18, 1, tzinfo=timezone.utc)  # recorded on a sealable day
        s.commit()
        added = digest.seal_through(s, str(tmp_path), date(2026, 10, 13), now=datetime(2026, 10, 14, 0, 5, tzinfo=timezone.utc))
        assert [r["count"] for r in added] == [1]
        assert digest.canonical_entries(s, date(2026, 10, 13))[0]["primary_signal"] == "insider_cluster_purchase"
        v = digest.verify_chain(s, str(tmp_path))
        assert v["ok"] is True and v["first_mismatch"] is None
        rows = journal.summary(s, {})
        assert (rows[0]["evaluation_horizon"], rows[0]["forward_test_label"]) == (5, "forward test of pre-registered finding")

    monkeypatch.setattr(main.state, "forward_evidence", None)
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    client = TestClient(main.app)
    [row] = client.get("/api/journal").json()["entries"]
    assert (row["evaluation_horizon"], row["forward_test_label"], row["direction"]) == (5, "forward test of pre-registered finding", "+")
    srow = client.get("/api/journal/summary").json()["rows"][0]
    assert srow["expected_5"] == 0.01609 and srow["evaluation_horizon"] == 5  # insider study micro / 5d row


def test_alerter_does_not_crash_on_forward_test_article(tmp_path):
    from app.alerts.service import Alerter

    aid = _insider_article(datetime.now(timezone.utc))
    cfg = SimpleNamespace(discord_webhook_url="https://discord.invalid/hook", alert_min_severity=2,
                          alert_max_age_minutes=15, alert_sizes=["nano", "micro", "small"])
    posted = []
    alerter = Alerter(cfg, main.evidence_for, post=lambda url, json, timeout: posted.append(json) or httpx.Response(204, request=httpx.Request("POST", url)))
    with SessionLocal() as s:
        entry = alerter.handle(s, aid)
        # format_message resolves forward-test codes through signal_def, so the alert goes out.
        assert entry is not None and entry.status == "sent", entry.status
        assert posted and "Insider" in str(posted[0])
        assert s.query(AlertLog).count() == 1
