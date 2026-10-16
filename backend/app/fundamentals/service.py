"""Dilution history and cash runway from SEC data (XBRL company facts + submissions).

These are the two things small-cap traders check first: how fast is the share
count growing, and how long until the company has to raise again.

- Cash: latest CashAndCashEquivalentsAtCarryingValue (falls back to the
  restricted-cash-inclusive tag).
- Burn: trailing-twelve-month operating cash flow. 10-Q cash flows are
  year-to-date, so TTM = last fiscal year + current YTD - prior-year same YTD.
- Runway: cash / monthly burn, as of the cash date. Raises after that date
  are listed separately, because they extend it.
- Dilution: change in dei:EntityCommonStockSharesOutstanding over ~1 year,
  plus every offering-type filing in the last 3 years.

All values are as reported; nothing is estimated beyond the arithmetic above.
"""

import json
import os
import time
from datetime import date, timedelta

import httpx

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
CACHE_MAX_AGE = 24 * 3600
CASH_TAGS = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
OCF_TAG = "NetCashProvidedByUsedInOperatingActivities"
DILUTION_FORMS = {"424B1", "424B2", "424B3", "424B4", "424B5", "S-1", "S-3", "F-1", "F-3"}


def _cached_json(url: str, path: str, user_agent: str) -> dict | None:
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_MAX_AGE:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    resp = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(resp.content)
    return resp.json()


def _units(facts: dict, ns: str, tag: str, unit: str) -> list[dict]:
    return (((facts.get("facts") or {}).get(ns) or {}).get(tag) or {}).get("units", {}).get(unit, [])


def _days(row: dict) -> int | None:
    if "start" not in row:
        return None
    return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days


def latest_cash(facts: dict) -> dict | None:
    for tag in CASH_TAGS:
        rows = _units(facts, "us-gaap", tag, "USD")
        if rows:
            r = max(rows, key=lambda x: (x["end"], x.get("filed", "")))
            return {"value": r["val"], "as_of": r["end"], "tag": tag}
    return None


def ttm_operating_cash_flow(facts: dict) -> dict | None:
    rows = [r for r in _units(facts, "us-gaap", OCF_TAG, "USD") if _days(r)]
    if not rows:
        return None
    annual = [r for r in rows if 340 <= _days(r) <= 380]
    if not annual:
        return None
    fy = max(annual, key=lambda r: (r["end"], r.get("filed", "")))
    fy_end = date.fromisoformat(fy["end"])
    # Year-to-date periods that started right after that fiscal year ended
    ytd = [r for r in rows if date.fromisoformat(r["start"]) == fy_end + timedelta(days=1) and _days(r) < 340]
    if not ytd:
        return {"value": fy["val"], "period_end": fy["end"], "method": "last fiscal year"}
    cur = max(ytd, key=lambda r: (r["end"], r.get("filed", "")))
    span = _days(cur)
    prior_start = date.fromisoformat(fy["start"])
    prior = [r for r in rows if date.fromisoformat(r["start"]) == prior_start and abs(_days(r) - span) <= 10]
    if not prior:
        return {"value": fy["val"], "period_end": fy["end"], "method": "last fiscal year"}
    p = max(prior, key=lambda r: r.get("filed", ""))
    return {"value": fy["val"] + cur["val"] - p["val"], "period_end": cur["end"], "method": "trailing twelve months"}


def runway(cash: dict | None, ocf: dict | None) -> dict:
    if not cash or not ocf:
        return {"status": "unknown"}
    if ocf["value"] >= 0:
        return {"status": "cash_flow_positive"}
    monthly_burn = -ocf["value"] / 12
    months = cash["value"] / monthly_burn if monthly_burn > 0 else None
    return {
        "status": "burning",
        "monthly_burn": round(monthly_burn),
        "months": round(months, 1) if months is not None else None,
        "runs_out_around": (date.fromisoformat(cash["as_of"]) + timedelta(days=int(months * 30.4))).isoformat() if months else None,
    }


def share_history(facts: dict) -> tuple[list[dict], dict | None]:
    rows = _units(facts, "dei", "EntityCommonStockSharesOutstanding", "shares")
    by_end: dict[str, int] = {}
    for r in sorted(rows, key=lambda x: x.get("filed", "")):
        by_end[r["end"]] = r["val"]  # later filings win
    hist = [{"date": d, "shares": v} for d, v in sorted(by_end.items())]
    if len(hist) < 2:
        return hist, None
    last = hist[-1]
    target = date.fromisoformat(last["date"]) - timedelta(days=365)
    base = min(hist[:-1], key=lambda h: abs((date.fromisoformat(h["date"]) - target).days))
    days = (date.fromisoformat(last["date"]) - date.fromisoformat(base["date"])).days
    if days < 180 or not base["shares"]:
        return hist, None
    return hist, {"from": base["date"], "to": last["date"], "change": round(last["shares"] / base["shares"] - 1, 4), "days": days}


def dilution_filings(sub: dict, since: date) -> list[dict]:
    recent = (sub.get("filings") or {}).get("recent") or {}
    out = []
    for i, form in enumerate(recent.get("form", [])):
        filed = recent["filingDate"][i]
        if filed < since.isoformat():
            continue
        items = (recent.get("items") or [""] * len(recent["form"]))[i] or ""
        is_pipe = form == "8-K" and "3.02" in items
        if form in DILUTION_FORMS or is_pipe:
            acc = recent["accessionNumber"][i]
            out.append({
                "form": form,
                "filed": filed,
                "kind": "unregistered sale (8-K 3.02)" if is_pipe else ("prospectus (priced)" if form.startswith("424B") else "registration"),
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(sub['cik'])}/{acc.replace('-', '')}/{acc}-index.htm",
            })
    return out


def company_profile(cik: int, data_dir: str, user_agent: str) -> dict:
    facts = _cached_json(COMPANYFACTS_URL.format(cik=cik), os.path.join(data_dir, "companyfacts", f"{cik}.json"), user_agent) or {}
    sub = _cached_json(SUBMISSIONS_URL.format(cik=cik), os.path.join(data_dir, "submissions_live", f"{cik}.json"), user_agent) or {}
    cash = latest_cash(facts)
    ocf = ttm_operating_cash_flow(facts)
    hist, change = share_history(facts)
    filings = dilution_filings(sub, date.today() - timedelta(days=3 * 365)) if sub else []
    raises_since_cash = [f for f in filings if cash and f["filed"] > cash["as_of"] and f["form"].startswith("424B")]
    return {
        "cik": cik,
        "cash": cash,
        "operating_cash_flow": ocf,
        "runway": runway(cash, ocf),
        "shares_history": hist[-12:],
        "share_change_1y": change,
        "dilution_filings": filings,
        "offerings_last_12m": sum(1 for f in filings if f["form"].startswith("424B") and f["filed"] >= (date.today() - timedelta(days=365)).isoformat()),
        "raises_since_cash_date": len(raises_since_cash),
    }
