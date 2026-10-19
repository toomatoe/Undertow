"""Insider Form 4 study: parser, data-set loader, filters, CMP classification, end-to-end offline run.

Never touches SEC or Yahoo: fixtures in tests/fixtures/form4/, synthetic zips and prices, httpx patched.
"""

import dataclasses
import importlib.util
import json
import os
import random
import re
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.insiders import classify, datasets, form4, study
from app.insiders.datasets import Owner, SchemaError
from app.research import eventstudy as es
from app.research import snapshot
from app.research.prices import PriceSeries
from app.schemas import Evidence

FIX = Path(__file__).parent / "fixtures" / "form4"
QZIP = FIX / "2024q1_form345.zip"


def _load_fixture_module():
    spec = importlib.util.spec_from_file_location("make_quarter_zip", FIX / "make_quarter_zip.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mqz = _load_fixture_module()


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


# --- form4.py --------------------------------------------------------------------


def test_parse_two_purchases_with_footnotes():
    doc = form4.parse_ownership_xml((FIX / "form4_two_purchases.xml").read_bytes())
    assert doc["document_type"] == "4" and doc["period"] == "2024-01-08" and doc["aff10b5one"] is False
    assert doc["issuer"] == {"cik": 1001, "ticker": "AAA", "name": "Alpha Example Corp"}
    assert doc["reporting_owners"] == [{"cik": 2001, "name": "Doe Jane", "is_director": True, "is_officer": False,
                                        "officer_title": None, "is_ten_percent": False}]
    txs = doc["transactions"]
    assert len(txs) == 2  # every block, and the nonDerivativeHolding is not a transaction
    assert txs[0] == {"security_title": "Common Stock", "date": "2024-01-08", "code": "P", "acquired_disposed": "A",
                      "shares": 600.0, "price": 15.0, "shares_after": 10600.0, "direct_indirect": "D"}
    assert txs[1]["date"] == "2024-01-09" and txs[1]["shares"] == 400.0 and txs[1]["direct_indirect"] == "I"


def test_parse_sparse_grant_tolerates_empty_values():
    doc = form4.parse_ownership_xml((FIX / "form4_sparse_grant.xml").read_bytes())
    assert doc["aff10b5one"] is None  # older schema: no aff10b5One element
    owner = doc["reporting_owners"][0]
    assert owner["is_director"] and owner["is_officer"] and owner["officer_title"] == "Chief Executive Officer"
    grant, exercise = doc["transactions"]
    assert grant["code"] == "A" and grant["price"] is None and grant["shares"] == 5000.0
    assert exercise["code"] == "M" and exercise["price"] is None  # 0 is implausible
    assert exercise["shares_after"] is None and exercise["direct_indirect"] is None


def test_namespaced_and_implausible_price():
    xml = (b'<ownershipDocument xmlns="http://example.invalid/ns"><documentType>4</documentType>'
           b'<nonDerivativeTable><nonDerivativeTransaction><transactionCoding><transactionCode>P</transactionCode>'
           b'</transactionCoding><transactionAmounts><transactionPricePerShare><value>2000000</value>'
           b'</transactionPricePerShare></transactionAmounts></nonDerivativeTransaction></nonDerivativeTable>'
           b'</ownershipDocument>')
    doc = form4.parse_ownership_xml(xml)
    assert doc["transactions"][0]["code"] == "P" and doc["transactions"][0]["price"] is None


@pytest.mark.parametrize("payload", [
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><ownershipDocument>&lol;</ownershipDocument>',
    b'<?xml version="1.0"?>\n<!doctype ownershipDocument SYSTEM "file:///etc/passwd"><ownershipDocument/>',
    b'<ownershipDocument><!ENTITY x "y"></ownershipDocument>',
])
def test_doctype_and_entity_rejected(payload):
    with pytest.raises(form4.UnsafeXMLError):
        form4.parse_ownership_xml(payload)


def test_malformed_and_wrong_root():
    with pytest.raises(ValueError):
        form4.parse_ownership_xml(b"<ownershipDocument>")
    with pytest.raises(ValueError):
        form4.parse_ownership_xml(b"<html/>")


def test_raw_xml_url_strips_xsl_prefix():
    assert form4.raw_xml_url(1001, "0000002001-24-000001", "xslF345X05/wk-form4_1704900000.xml") == (
        "https://www.sec.gov/Archives/edgar/data/1001/000000200124000001/wk-form4_1704900000.xml")
    assert form4.raw_xml_url("0000001001", "0000002001-24-000001", "xslF345X03/doc4.xml").endswith("/doc4.xml")
    assert form4.raw_xml_url(1001, "0000002001-24-000001", "form4.xml").endswith("/000000200124000001/form4.xml")


def test_parser_needs_no_new_dependency():
    src = (Path(study.__file__).parent / "form4.py").read_text()
    imports = set(re.findall(r"^(?:import|from) (\w+)", src, re.M))
    assert imports <= {"re", "xml", "datetime"}


# --- datasets.py -----------------------------------------------------------------


def test_load_quarter_joins_three_tables():
    rows = datasets.load_quarter(str(QZIP))
    assert len(rows) == 14  # 15 transaction rows minus the orphan
    a1 = [r for r in rows if r.accession == "0000002001-24-000001"]
    assert [(r.trans_date, r.code, r.shares, r.price) for r in a1] == [
        (date(2024, 1, 8), "P", 600.0, 15.0), (date(2024, 1, 9), "P", 400.0, 15.0)]
    r = a1[0]
    assert r.filing_date == date(2024, 1, 10) and r.document_type == "4" and r.issuer_cik == 1001
    assert r.issuer_ticker == "AAA" and r.aff10b5one is False and r.value == 9000.0
    assert r.owners == (Owner(2001, "Doe Jane", True, False, False, ""),)
    joint = [r for r in rows if r.accession == "0000002005-24-000001"][0]
    assert [o.cik for o in joint.owners] == [2005, 2006]
    assert joint.owners[0].is_director and joint.owners[0].is_officer and joint.owners[1].is_ten_percent
    assert [r for r in rows if r.accession == "0000002002-24-000001"][0].aff10b5one is None  # blank
    assert datasets.load_quarter(str(QZIP), codes=("S",))[0].acquired_disposed == "D"


def _rewrite_zip(src: Path, dst: Path, table: str, transform) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for name in zin.namelist():
            text = zin.read(name).decode()
            zout.writestr(name, transform(text) if name.startswith(table) else text)


def test_schema_drift_fails_clearly(tmp_path):
    bad = tmp_path / "bad.zip"
    _rewrite_zip(QZIP, bad, "NONDERIV_TRANS", lambda t: t.replace("TRANS_PRICEPERSHARE\t", "TRANS_PRICE\t", 1))
    with pytest.raises(SchemaError, match=r"NONDERIV_TRANS.*TRANS_PRICEPERSHARE"):
        datasets.load_quarter(str(bad))
    missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(missing, "w") as z:
        z.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\n")
    with pytest.raises(SchemaError):
        datasets.load_quarter(str(missing))


def test_optional_aff10b5one_column(tmp_path):
    old = tmp_path / "old.zip"

    def drop_last_column(text):
        return "\n".join(line.rsplit("\t", 1)[0] for line in text.split("\n"))

    _rewrite_zip(QZIP, old, "SUBMISSION", drop_last_column)
    assert all(r.aff10b5one is None for r in datasets.load_quarter(str(old)))


def test_parse_helpers():
    assert datasets.parse_date("15-JAN-2024") == date(2024, 1, 15)
    assert datasets.parse_date("15-Jan-2024") == date(2024, 1, 15)
    assert datasets.parse_date("2024-01-15") == date(2024, 1, 15)
    assert datasets.parse_date("") is None and datasets.parse_date("garbage") is None
    assert datasets.parse_relationship("Director,Officer,TenPercentOwner") == (True, True, True)
    assert datasets.parse_relationship("TenPercentOwner") == (False, False, True)
    assert datasets.parse_relationship("Other") == (False, False, False)
    assert datasets.quarters_between((2023, 3), (2024, 2)) == [(2023, 3), (2023, 4), (2024, 1), (2024, 2)]


def test_download_quarter_offline_never_fetches(no_network, tmp_path):
    assert datasets.download_quarter(2024, 1, str(tmp_path), "ua", offline=True) is None
    assert snapshot.misses()[-1].endswith("2024q1_form345.zip")
    os.makedirs(tmp_path / "insider_datasets")
    shutil.copy(QZIP, tmp_path / "insider_datasets" / "2024q1_form345.zip")
    assert datasets.download_quarter(2024, 1, str(tmp_path), "ua", offline=True).endswith("2024q1_form345.zip")


def test_download_quarter_caches_with_user_agent(monkeypatch, tmp_path):
    calls = []

    class Resp:
        status_code = 200
        content = QZIP.read_bytes()

        def raise_for_status(self):
            pass

    def fake_get(url, headers=None, **kw):
        calls.append((url, headers))
        return Resp()

    monkeypatch.setattr(datasets.httpx, "get", fake_get)
    monkeypatch.setattr(datasets.time, "sleep", lambda s: None)
    p1 = datasets.download_quarter(2024, 1, str(tmp_path), "Research bot admin@example.com")
    p2 = datasets.download_quarter(2024, 1, str(tmp_path), "Research bot admin@example.com")
    assert p1 == p2 and os.path.exists(p1) and len(calls) == 1
    assert calls[0][0].endswith("/2024q1_form345.zip") and calls[0][1] == {"User-Agent": "Research bot admin@example.com"}
    assert datasets.MIN_INTERVAL >= 0.125  # at most 8 requests per second


# --- filters, aggregation, cluster -------------------------------------------------


def _fixture_data(tmp_path) -> study.InsiderData:
    os.makedirs(tmp_path / "insider_datasets", exist_ok=True)
    shutil.copy(QZIP, tmp_path / "insider_datasets" / "2024q1_form345.zip")
    return study.load_insider_data(str(tmp_path), "ua", offline=True, quarters=[(2024, 1)])


def test_filters_on_fixture_quarter(no_network, tmp_path):
    data = _fixture_data(tmp_path)
    s = data.stats
    assert s["p_rows"] == 12 and s["qualifying_purchases"] == 7
    assert s["excluded_not_director_or_officer"] == 1  # A3, 10%-only owner
    assert s["excluded_not_form4"] == 1  # A4, 4/A
    assert s["excluded_aff10b5one"] == 1  # A6
    assert s["excluded_no_shares_or_price"] == 1  # A8, price 0
    assert s["excluded_not_open_market_purchase"] == 1  # C1, acquired/disposed D
    assert {p.accession for p in data.purchases} == {
        "0000002001-24-000001", "0000002002-24-000001", "0000002002-24-000002",
        "0000002004-24-000002", "0000002005-24-000001"}
    joint = [p for p in data.purchases if p.accession == "0000002005-24-000001"]
    assert {p.insider_cik for p in joint} == {2005}  # the director/officer, not the 10% trust


def test_per_issuer_day_aggregation_and_cluster(no_network, tmp_path):
    events = study.build_events(_fixture_data(tmp_path))
    aaa = sorted((sig, d) for sig, d, _ in events[1001])
    assert aaa == [
        (study.CLUSTER, date(2024, 1, 10)), (study.CLUSTER, date(2024, 2, 8)),
        (study.PURCHASE, date(2024, 1, 10)), (study.PURCHASE, date(2024, 2, 8)),
    ]  # 2024-02-01 ($5,000) is below the minimum but still counts toward the Feb 8 cluster
    jan10 = [a for sig, d, a in events[1001] if sig == study.PURCHASE and d == date(2024, 1, 10)][0]
    assert jan10 == ("0000002001-24-000001", "0000002002-24-000001")
    assert events[1002] == [(study.PURCHASE, date(2024, 2, 12), ("0000002005-24-000001",))]
    assert 1003 not in events
    # No 2021-2023 history in this fixture: everyone is unclassified.
    assert not any(sig in (study.OPPORTUNISTIC_SIGNAL, study.ROUTINE_SIGNAL) for evs in events.values() for sig, _, _ in evs)


def _purchase(issuer, insider, d, value=20_000.0, acc=None):
    return study.Purchase(issuer, insider, d, d, value, acc or f"{insider}-{d}")


def test_cluster_window_is_ten_calendar_days():
    data = study.InsiderData()
    data.purchases = [_purchase(1, 10, date(2024, 3, 1)), _purchase(1, 11, date(2024, 3, 11)),
                      _purchase(1, 12, date(2024, 4, 1)), _purchase(1, 12, date(2024, 4, 5)),
                      _purchase(1, 13, date(2024, 4, 16))]
    sig = {(s, d) for s, d, _ in study.build_events(data)[1]}
    assert (study.CLUSTER, date(2024, 3, 11)) in sig  # exactly 10 days after the first buyer
    assert (study.CLUSTER, date(2024, 3, 1)) not in sig  # first buyer alone
    assert (study.CLUSTER, date(2024, 4, 5)) not in sig  # the same insider again is not a new buyer
    assert (study.CLUSTER, date(2024, 4, 16)) not in sig  # 11 days after insider 12's last buy
    assert (study.PURCHASE, date(2024, 4, 16)) in sig


def test_cluster_counts_repeat_buyer_inside_window():
    data = study.InsiderData()
    data.purchases = [_purchase(1, 12, date(2024, 4, 1)), _purchase(1, 12, date(2024, 4, 5)),
                      _purchase(1, 13, date(2024, 4, 12)), _purchase(1, 14, date(2024, 5, 1)),
                      _purchase(1, 15, date(2024, 5, 12))]
    sig = {(s, d) for s, d, _ in study.build_events(data)[1]}
    assert (study.CLUSTER, date(2024, 4, 12)) in sig  # insider 12 bought Apr 5, inside [Apr 2, Apr 12]
    assert (study.CLUSTER, date(2024, 5, 12)) not in sig  # insider 14's buy is 11 days earlier


def test_events_outside_window_and_min_value():
    data = study.InsiderData()
    data.purchases = [_purchase(1, 10, date(2023, 9, 25)), _purchase(1, 11, date(2023, 10, 2), value=9_999.0),
                      _purchase(1, 12, date(2026, 7, 1)), _purchase(1, 13, date(2023, 10, 3), value=6_000.0),
                      _purchase(1, 14, date(2023, 10, 3), value=4_000.0, acc="x2")]
    sig = sorted((s, d) for s, d, _ in study.build_events(data)[1])
    # Sep 25 is before the window, Oct 2 below $10k, Jul 2026 after; Oct 3 aggregates two filings to $10k
    # and is a cluster (insiders 10, 11, 13, 14 within 10 days).
    assert sig == [(study.CLUSTER, date(2023, 10, 3)), (study.PURCHASE, date(2023, 10, 3))]


# --- day 0 -------------------------------------------------------------------------


def _bdays(a, b, skip=()):
    out, d = [], a
    while d <= b:
        if d.weekday() < 5 and d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_day0_is_next_trading_day_after_filing_date():
    days = _bdays(date(2024, 1, 2), date(2024, 2, 29), skip={date(2024, 1, 15)})  # MLK day
    series = PriceSeries("AAA", days, [10.0 + i for i in range(len(days))])
    for filed, expected in [(date(2024, 1, 10), date(2024, 1, 11)),  # Wednesday -> Thursday
                            (date(2024, 1, 12), date(2024, 1, 16)),  # Friday before a holiday -> Tuesday
                            (date(2024, 1, 13), date(2024, 1, 16))]:  # Saturday filing
        i = es.day0_index(series, study.day0_datetime(filed))
        assert series.dates[i] == expected and series.dates[i] != filed


# --- CMP classification ------------------------------------------------------------


def test_classify_routine_opportunistic_unclassified():
    d = date
    routine = [d(2021, 6, 3), d(2022, 6, 20), d(2023, 6, 1), d(2023, 2, 1)]
    assert classify.classify_trades(routine, 2024) == classify.ROUTINE
    opportunistic = [d(2021, 1, 5), d(2022, 5, 5), d(2023, 9, 5)]
    assert classify.classify_trades(opportunistic, 2024) == classify.OPPORTUNISTIC
    assert classify.classify_trades([d(2021, 6, 1), d(2023, 6, 1)], 2024) is None  # no 2022 trade
    assert classify.classify_trades([d(2020, 6, 1), d(2021, 6, 1), d(2022, 6, 1)], 2024) is None  # stale history
    assert classify.classify_trades([], 2024) is None
    # Same month in only two of the three years -> opportunistic.
    assert classify.classify_trades([d(2021, 6, 1), d(2022, 6, 1), d(2023, 7, 1)], 2024) == classify.OPPORTUNISTIC
    # Trades in the event year itself do not count as history.
    assert classify.classify_trades([d(2021, 6, 1), d(2022, 6, 1), d(2024, 6, 1)], 2024) is None


def test_trade_history_is_point_in_time():
    h = classify.TradeHistory()
    h.add(7, date(2021, 3, 1), date(2021, 3, 2))
    h.add(7, date(2022, 3, 1), date(2022, 3, 2))
    h.add(7, date(2023, 3, 1), date(2024, 5, 1))  # late filing, after the event below
    h.add(7, None, date(2023, 1, 1))  # ignored
    assert h.classify(7, 2024, as_of=date(2024, 2, 1)) is None
    assert h.classify(7, 2024, as_of=date(2024, 5, 1)) == classify.ROUTINE
    assert h.classify(8, 2024, as_of=date(2024, 5, 1)) is None
    assert len(h) == 3


def test_classified_signals_split_by_insider():
    data = study.InsiderData()
    for y in (2021, 2022, 2023):
        data.history.add(20, date(y, 6, 10), date(y, 6, 12))  # routine
        data.history.add(21, date(y, 2 + y - 2021, 10), date(y, 6, 12))  # opportunistic
    data.purchases = [_purchase(1, 20, date(2024, 3, 4)), _purchase(1, 21, date(2024, 3, 4), value=8_000.0),
                      _purchase(1, 22, date(2024, 3, 4))]  # 22: no history, unclassified
    sig = {s for s, _, _ in study.build_events(data)[1]}
    # opportunistic total is $8,000 < $10,000, so only the routine signal fires
    assert sig == {study.PURCHASE, study.CLUSTER, study.ROUTINE_SIGNAL}


# --- pre-registration consistency ---------------------------------------------------


def test_constants_match_preregistration():
    text = (Path(study.__file__).parent / "PREREGISTRATION.md").read_text()
    assert "2026-10-19" in text and study.PREREGISTERED_ON == "2026-10-19"
    assert study.DESIGN.name == "insider_purchases" and study.DESIGN.seed == 11 and study.DESIGN.float_year == 2023
    assert dict(study.DESIGN.sizes) == {"nano": 300, "micro": 400, "small": 400, "large": 100}
    assert "nano 300, micro 400, small 400, large 100" in text and "**11**" in text
    assert study.DESIGN.window == (date(2023, 10, 1), date(2026, 6, 30)) and "2023-10-01 to 2026-06-30" in text
    assert study.HISTORY_QUARTERS == ((2020, 1), (2026, 2)) and "2020Q1 to 2026Q2" in text
    assert study.MIN_VALUE == 10_000 and "$10,000" in text
    assert study.CLUSTER_DAYS == 10 and study.CROSSCHECK_N == 50
    assert set(study.SIGNAL_DEFS) == {"insider_purchase", "insider_cluster_purchase",
                                      "insider_purchase_opportunistic", "insider_purchase_routine"}
    assert all(f"`{code}`" in text for code in study.SIGNAL_DEFS)
    assert all(s.direction == "+" for s in study.SIGNAL_DEFS.values())
    assert study.DESIGN.results_file == "event_study_insider_purchases.json"


def test_main_signal_taxonomy_untouched():
    from app.pipeline.signals import ALL_SIGNALS

    assert not any(code.startswith("insider") for code in ALL_SIGNALS)


# --- end to end (offline, synthetic) ---------------------------------------------------

N_COMPANIES = 12
FIRST_DIRECTOR = 5000
SECOND_INSIDER = 6000


def _fmt(d: date) -> str:
    return d.strftime("%d-%b-%Y").upper()


def _quarter(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def _write_world(data_dir: Path, design) -> dict:
    """Frame, submissions, data-set zips (history 2021-2023, events 2024) and Form 4 XML cache."""
    filings: dict[tuple[int, int], list] = {}

    def add(acc, filed, issuer, owner_cik, rel, tx_rows):
        filings.setdefault(_quarter(filed), []).append((acc, filed, issuer, owner_cik, rel, tx_rows))

    accessions: dict[int, list[str]] = {}
    for c in range(1, N_COMPANIES + 1):
        director = FIRST_DIRECTOR + c
        months = [6, 6, 6] if c % 2 == 0 else [1, 5, 9]  # even: routine, odd: opportunistic
        for k, (y, m) in enumerate(zip((2021, 2022, 2023), months)):
            d = date(y, m, 10)
            add(f"{director:010d}-{y % 100}-9{k:05d}", d + timedelta(days=2), c, director, "Director",
                [(d, "S", 1000, 12.0, "D")])
        accessions[c] = []
        for k in range(4):
            d = date(2024, 1, 8) + timedelta(days=21 * k + c)
            acc = f"{director:010d}-24-{k:06d}"
            accessions[c].append(acc)
            add(acc, d + timedelta(days=2), c, director, "Director", [(d, "P", 1000, 20.0 + c, "A")])
        # a second insider (officer, no history) buys two days after the first event -> cluster
        d = date(2024, 1, 8) + timedelta(days=c + 2)
        acc = f"{SECOND_INSIDER + c:010d}-24-000000"
        accessions[c].append(acc)
        add(acc, d + timedelta(days=2), c, SECOND_INSIDER + c, "Officer", [(d, "P", 750, 20.0 + c, "A")])

    os.makedirs(data_dir / "insider_datasets", exist_ok=True)
    for (y, q), fs in filings.items():
        subs, owners, trans = [], [], []
        for acc, filed, issuer, owner_cik, rel, tx_rows in fs:
            subs.append([acc, _fmt(filed), _fmt(filed), "", "0", "0", "", "", "4", str(issuer), f"Co {issuer}",
                         f"T{issuer}", "", "0"])
            owners.append([acc, str(owner_cik), f"Person {owner_cik}", rel, "", "", "", "", "", "", "", "", ""])
            for td, code, sh, px, ad in tx_rows:
                trans.append([acc, "1", "Common Stock", "", _fmt(td), "", "", "", "4", code, "0", "", "", "",
                              str(sh), "", str(px), "", ad, "", "1", "", "", "", "D", "", "", ""])
        with zipfile.ZipFile(data_dir / "insider_datasets" / f"{y}q{q}_form345.zip", "w") as z:
            z.writestr("SUBMISSION.tsv", mqz.tsv(mqz.SUBMISSION_COLS, subs))
            z.writestr("REPORTINGOWNER.tsv", mqz.tsv(mqz.OWNER_COLS, owners))
            z.writestr("NONDERIV_TRANS.tsv", mqz.tsv(mqz.TRANS_COLS, trans))

    frame = {"data": [{"cik": c, "val": 20e6, "end": f"{design.float_year}-06-30"} for c in range(1, N_COMPANIES + 1)]}
    with open(es.frame_path(str(data_dir), design.float_year), "w") as f:
        json.dump(frame, f)
    os.makedirs(data_dir / "submissions", exist_ok=True)
    os.makedirs(data_dir / study.XML_CACHE_SUBDIR, exist_ok=True)
    template = (FIX / "form4_two_purchases.xml").read_text()
    by_acc = {f[0]: f for fs in filings.values() for f in fs}
    for c in range(1, N_COMPANIES + 1):
        sub = {"entityType": "operating", "sic": "2834", "tickers": [f"T{c}"],
               "filings": {"recent": {"accessionNumber": accessions[c],
                                      "primaryDocument": ["xslF345X05/form4.xml"] * len(accessions[c])},
                           "files": []}}
        (data_dir / "submissions" / f"{c}.json").write_text(json.dumps(sub))
        for acc in accessions[c]:
            td, code, sh, px, _ = by_acc[acc][5][0]
            if c == 1:
                px += 1.0  # company 1: dataset and XML disagree on price
            xml = template.replace("<value>2024-01-08</value>", f"<value>{td.isoformat()}</value>", 1)
            xml = xml.replace("<value>600</value>", f"<value>{sh}</value>", 1)
            xml = xml.replace("<value>15.00</value>", f"<value>{px}</value>", 1)
            (data_dir / study.XML_CACHE_SUBDIR / f"{acc}.xml").write_text(xml)
    quarters = sorted(filings)
    return {"quarters": quarters, "accessions": accessions}


def _stub_prices(monkeypatch):
    def prices(ticker, start, end, cache_dir, *a, **k):
        days = _bdays(start, end)
        rng = random.Random(sum(map(ord, ticker)))
        drift = 0.002 if ticker.startswith("T") else 0.0002
        px, closes = 10.0, []
        for _ in days:
            px *= 1 + rng.gauss(drift, 0.02)
            closes.append(px)
        return PriceSeries(ticker, days, closes)

    monkeypatch.setattr(es, "load_prices", prices)

    def no_sleep(s):
        raise AssertionError("slept in offline mode")

    monkeypatch.setattr(es.time, "sleep", no_sleep)
    monkeypatch.setattr(datasets.time, "sleep", no_sleep)


ROW_KEYS = {"signal", "label", "direction", "bucket", "horizon_days", "n", "companies", "mean_reaction",
            "mean_abnormal", "median_abnormal", "t_stat", "hit_rate", "cost", "borrow", "mean_net", "baseline_mean",
            "excess_vs_baseline", "t_vs_baseline", "t_stat_clustered", "t_vs_baseline_clustered", "clusters",
            "significant", "nominal_significant"}


def test_study_end_to_end_offline(no_network, monkeypatch, tmp_path):
    _stub_prices(monkeypatch)
    design = dataclasses.replace(study.DESIGN, sizes={"nano": N_COMPANIES})
    world = _write_world(tmp_path, design)
    out = study.run(offline=True, data_dir=str(tmp_path), user_agent="ua", quarters=world["quarters"], design=design)

    # Same top-level schema as event_study.json, plus the insider additions.
    reference = es.build_study(design, [], {}, study.SIGNAL_DEFS)
    assert set(reference) <= set(out)
    assert set(reference["config"]) <= set(out["config"])
    assert out["config"]["study"] == "insider_purchases"
    assert out["preregistration"] == "backend/app/insiders/PREREGISTRATION.md"
    assert out["coverage"]["nano"]["companies"] == N_COMPANIES and out["coverage"]["nano"]["ok"] == N_COMPANIES

    rows = {(r["signal"], r["horizon_days"]): r for r in out["results"]}
    assert set(rows) == {(s, h) for s in (study.PURCHASE, study.OPPORTUNISTIC_SIGNAL, study.ROUTINE_SIGNAL)
                         for h in (5, 20)}  # cluster events (12) are below MIN_N
    assert rows[(study.PURCHASE, 20)]["n"] == 5 * N_COMPANIES
    assert rows[(study.OPPORTUNISTIC_SIGNAL, 20)]["n"] == 4 * N_COMPANIES // 2
    assert rows[(study.ROUTINE_SIGNAL, 20)]["n"] == 4 * N_COMPANIES // 2
    for r in out["results"]:
        assert ROW_KEYS <= set(r) and "significant_unclustered" in r
        assert r["borrow"] == 0.0 and r["direction"] == "+"
        Evidence(**{k: r[k] for k in Evidence.model_fields})  # the API/Lab loader accepts the rows
    assert out["testing"]["n_tests"] == 6 and "significance_rule" in out["testing"]
    assert out["measured_events"] == 5 * N_COMPANIES + 4 * N_COMPANIES + N_COMPANIES  # purchase + classified + cluster

    comp = out["opportunistic_vs_routine"]
    assert [(c["bucket"], c["horizon_days"]) for c in comp] == [("nano", 5), ("nano", 20)]

    q = out["data_quality"]
    assert q["xml_crosscheck_n"] == study.CROSSCHECK_N and q["unavailable"] == 0
    bad = set(world["accessions"][1])
    assert set(q["mismatched_accessions"]) <= bad and q["mismatched_accessions"]
    assert q["match_rate"] == round((q["xml_crosscheck_n"] - len(q["mismatched_accessions"])) / q["xml_crosscheck_n"], 4)
    assert q["datasets"]["quarters_missing"] == [] and q["datasets"]["qualifying_purchases"] == 5 * N_COMPANIES
    json.dumps(out)  # serializable

    # Deterministic: the same inputs give the same results.
    again = study.run(offline=True, data_dir=str(tmp_path), user_agent="ua", quarters=world["quarters"], design=design)
    assert snapshot.results_sha256(again) == snapshot.results_sha256(out)


def test_significance_rule_uses_clustered_t():
    row = {"t_stat": 9.0, "t_stat_clustered": 1.0, "t_vs_baseline": 9.0, "mean_abnormal": 0.05,
           "excess_vs_baseline": 0.04, "mean_net": 0.02, "significant": True}
    doc = {"testing": {"n_tests": 4}, "results": [dict(row), dict(row, t_stat_clustered=5.0),
                                                   dict(row, t_stat_clustered=5.0, t_vs_baseline=1.0),
                                                   dict(row, t_stat_clustered=5.0, mean_net=-0.01)]}
    study.apply_significance(doc)
    assert [r["significant"] for r in doc["results"]] == [False, True, False, False]
    assert all(r["significant_unclustered"] for r in doc["results"])
    assert study.t_critical(4) == pytest.approx(2.498, abs=1e-3)


def test_cli_offline_writes_file_and_guards_live_results(no_network, monkeypatch, tmp_path):
    from app.config import get_settings

    _stub_prices(monkeypatch)
    small = dataclasses.replace(study.DESIGN, sizes={"nano": N_COMPANIES})
    world = _write_world(tmp_path, small)
    monkeypatch.setattr(study, "DESIGN", small)
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    qs = [f"{y}q{q}" for y, q in world["quarters"]]
    with pytest.raises(SystemExit):
        study.main(["--offline", "--quarters", *qs, "--output", str(tmp_path / "event_study.json")])
    # The registered quarter list includes quarters not in this synthetic cache: misses fail loudly...
    with pytest.raises(SystemExit):
        study.main(["--offline"])
    # ...and --allow-missing still writes, recording the misses.
    snapshot.start_tracking()
    study.main(["--offline", "--allow-missing", "--quarters", *qs])
    written = json.loads((tmp_path / "event_study_insider_purchases.json").read_text())
    assert written["config"]["study"] == "insider_purchases" and written["inputs_manifest"].startswith("snapshots/")
    assert written["config"]["quarters_override"] == qs
    assert written["offline_misses"] == 0


def test_parse_quarter_arg():
    assert study.parse_quarter("2024Q1") == (2024, 1)
    with pytest.raises(Exception):
        study.parse_quarter("2024-1")
