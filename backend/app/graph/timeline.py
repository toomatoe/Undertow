"""Per-cluster item counts over the selection window, hourly (days <= 3) or daily."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta


def granularity(days: int) -> str:
    return "hour" if days <= 3 else "day"


def _floor(ts: datetime, gran: str) -> datetime:
    if gran == "hour":
        return ts.replace(minute=0, second=0, microsecond=0)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def build_timeline(start: datetime, end: datetime, days: int, points: list[tuple[datetime, int]]) -> dict:
    """`points` = (published_at UTC, cluster id). Buckets cover [floor(start), end] including empty ones;
    each bucket lists only nonzero cluster counts, keyed by str(cluster id)."""
    gran = granularity(days)
    step = timedelta(hours=1) if gran == "hour" else timedelta(days=1)
    counts: dict[datetime, Counter] = {}
    for ts, cid in points:
        counts.setdefault(_floor(ts, gran), Counter())[str(cid)] += 1
    buckets = []
    t = _floor(start, gran)
    last = _floor(end, gran)
    while t <= last:
        c = counts.get(t, Counter())
        buckets.append({"t": t, "counts": {k: c[k] for k in sorted(c, key=lambda s: int(s)) if c[k]}})
        t += step
    return {"granularity": gran, "buckets": buckets}
