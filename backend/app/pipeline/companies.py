"""Company size from SEC XBRL public float (dei:EntityPublicFloat).

Public float is the market value of shares held by non-affiliates, reported on
the 10-K cover page as of the end of Q2. It is free, public domain, covers
every filer in one request, and is a decent size proxy (it understates market
cap for insider-heavy companies). We use it instead of price x shares so size
needs no price feed.
"""

import json
import logging
import os
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

FRAME_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY{year}Q2I.json"
CACHE_MAX_AGE = 7 * 24 * 3600

# (bucket, upper bound in USD) - conventional cut-offs, applied to public float
BUCKETS = [
    ("nano", 50e6),
    ("micro", 300e6),
    ("small", 2e9),
    ("mid", 10e9),
    ("large", float("inf")),
]
BUCKET_NAMES = [b for b, _ in BUCKETS]


def bucket_for(public_float: float | None) -> str | None:
    if public_float is None or public_float <= 0:
        return None
    for name, upper in BUCKETS:
        if public_float < upper:
            return name
    return None


@dataclass(frozen=True)
class FloatRecord:
    cik: int
    public_float: float
    as_of: str  # YYYY-MM-DD the float was measured


def parse_frame(data: dict) -> dict[int, FloatRecord]:
    out: dict[int, FloatRecord] = {}
    for row in data.get("data", []):
        rec = FloatRecord(cik=int(row["cik"]), public_float=float(row["val"]), as_of=row["end"])
        prev = out.get(rec.cik)
        if prev is None or rec.as_of > prev.as_of:
            out[rec.cik] = rec
    return out


def fetch_frame(year: int, data_dir: str, user_agent: str, max_age: float = CACHE_MAX_AGE) -> dict[int, FloatRecord]:
    """One year's Q2 float frame, cached on disk. Returns {} if unavailable."""
    path = os.path.join(data_dir, f"public_float_CY{year}Q2I.json")
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age
    if not fresh:
        try:
            resp = httpx.get(FRAME_URL.format(year=year), headers={"User-Agent": user_agent}, timeout=60)
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            os.makedirs(data_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(resp.content)
        except Exception as exc:
            log.warning("Could not fetch public float frame CY%s: %s", year, exc)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return parse_frame(json.load(f))


def load_latest_floats(data_dir: str, user_agent: str, current_year: int) -> dict[int, FloatRecord]:
    """Merge recent Q2 frames, keeping the most recent value per company.

    The current year's frame fills in gradually as 10-Ks are filed, so older
    years backfill companies that have not filed one yet.
    """
    merged: dict[int, FloatRecord] = {}
    for year in (current_year - 2, current_year - 1, current_year):
        for cik, rec in fetch_frame(year, data_dir, user_agent).items():
            merged[cik] = rec  # later years overwrite earlier
    return merged


def sync_companies(universe, floats: dict[int, FloatRecord]) -> int:
    """Replace the companies table with the current ticker universe and size buckets."""
    from sqlalchemy import delete

    from app.db import SessionLocal
    from app.models import Company

    rows = []
    for c in universe.by_ticker.values():
        rec = floats.get(c.cik)
        rows.append(
            {
                "symbol": c.ticker,
                "cik": c.cik,
                "name": c.name[:256],
                "public_float": int(rec.public_float) if rec else None,
                "float_as_of": rec.as_of if rec else None,
                "size_bucket": bucket_for(rec.public_float) if rec else None,
            }
        )
    with SessionLocal() as session:
        session.execute(delete(Company))
        if rows:
            session.execute(Company.__table__.insert(), rows)
        session.commit()
    return len(rows)
