from datetime import date, timedelta

from app.fundamentals.service import dilution_filings, latest_cash, runway, share_history, ttm_operating_cash_flow


def facts(ocf=None, cash=None, shares=None):
    return {"facts": {
        "us-gaap": {
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf or []}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": cash or []}},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": shares or []}}},
    }}


OCF = [
    {"start": "2025-01-01", "end": "2025-12-31", "val": -60_000_000, "filed": "2026-03-01"},  # FY2025
    {"start": "2025-01-01", "end": "2025-06-30", "val": -40_000_000, "filed": "2025-08-01"},  # prior-year H1
    {"start": "2026-01-01", "end": "2026-03-31", "val": -10_000_000, "filed": "2026-05-01"},  # Q1 YTD
    {"start": "2026-01-01", "end": "2026-06-30", "val": -20_000_000, "filed": "2026-08-01"},  # H1 YTD
]


def test_ttm_uses_fiscal_year_plus_ytd_minus_prior_ytd():
    t = ttm_operating_cash_flow(facts(ocf=OCF))
    assert t == {"value": -60e6 - 20e6 + 40e6, "period_end": "2026-06-30", "method": "trailing twelve months"}


def test_ttm_falls_back_to_fiscal_year():
    t = ttm_operating_cash_flow(facts(ocf=OCF[:1]))
    assert t["method"] == "last fiscal year" and t["value"] == -60e6


def test_runway_math():
    cash = latest_cash(facts(cash=[{"end": "2026-03-31", "val": 5e6}, {"end": "2026-06-30", "val": 12e6, "filed": "x"}]))
    assert cash["value"] == 12e6 and cash["as_of"] == "2026-06-30"
    r = runway(cash, {"value": -24e6})
    assert r["monthly_burn"] == 2_000_000 and r["months"] == 6.0
    assert r["runs_out_around"].startswith("2026-12")
    assert runway(cash, {"value": 1e6}) == {"status": "cash_flow_positive"}
    assert runway(None, None) == {"status": "unknown"}


def test_share_change_over_a_year():
    rows = [{"end": "2025-07-31", "val": 100, "filed": "a"}, {"end": "2026-01-31", "val": 150, "filed": "b"},
            {"end": "2026-07-31", "val": 300, "filed": "c"}]
    hist, change = share_history(facts(shares=rows))
    assert len(hist) == 3 and change["change"] == 2.0 and change["from"] == "2025-07-31"


def test_dilution_filings_filter():
    today = date.today()
    sub = {"cik": "123", "filings": {"recent": {
        "form": ["424B5", "8-K", "8-K", "10-Q", "S-3", "424B5"],
        "filingDate": [today.isoformat(), today.isoformat(), today.isoformat(), today.isoformat(), today.isoformat(),
                       (today - timedelta(days=4 * 365)).isoformat()],
        "items": ["", "3.02,9.01", "2.02", "", "", ""],
        "accessionNumber": ["0000000001-26-000001"] * 6,
    }}}
    got = dilution_filings(sub, today - timedelta(days=3 * 365))
    assert [g["form"] for g in got] == ["424B5", "8-K", "S-3"]
    assert got[1]["kind"] == "unregistered sale (8-K 3.02)"
