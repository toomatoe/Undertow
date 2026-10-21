"""Edge builders, after the contextual / spatial / temporal edge families of CaST (Duong, Nguyen, Levin & Gary,
arXiv 2602.02601), adapted to filings and news.

Every edge is an ASSOCIATION or PROXIMITY between two items (similar wording, same company, close in time). An edge
never means that one item led to the other.

Internally nodes are indices 0..n-1 in Article.id order, so "smaller index" == "smaller id". Edges are tuples
(type, a, b, weight). Undirected types (contextual, spatial) have a < b and are deduplicated; temporal edges point
from the earlier item to the later one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from app.graph.smooth import Neighbours

SIZE_BUCKET_WEIGHT = 0.15
SIZE_BUCKET_MAX_N = 60  # weak same-size-bucket edges only on small graphs (they add little on big ones)

Edge = tuple[str, int, int, float]


@dataclass
class Item:
    idx: int
    ts: datetime
    tickers: list[str]
    size_bucket: str | None


def _order(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda it: (it.ts, it.idx))


def contextual_edges(neighbours: Neighbours, threshold: float) -> list[Edge]:
    """Undirected union of each node's top-k neighbours with similarity >= threshold (max weight kept on dedupe)."""
    best: dict[tuple[int, int], float] = {}
    for i, nb in enumerate(neighbours):
        for j, w in nb:
            if w < threshold or i == j:
                continue
            key = (min(i, j), max(i, j))
            if w > best.get(key, -1.0):
                best[key] = w
    return [("contextual", a, b, round(min(1.0, w), 6)) for (a, b), w in sorted(best.items())]


def spatial_ticker_edges(items: list[Item]) -> list[Edge]:
    """Same company: consecutive-in-time items per ticker (a chain, not a clique), weight 1.0."""
    by_ticker: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        for t in dict.fromkeys(it.tickers):
            by_ticker[t].append(it)
    seen: set[tuple[int, int]] = set()
    for t in sorted(by_ticker):
        chain = _order(by_ticker[t])
        for x, y in zip(chain, chain[1:]):
            seen.add((min(x.idx, y.idx), max(x.idx, y.idx)))
    return [("spatial", a, b, 1.0) for a, b in sorted(seen)]


def size_bucket_edges(items: list[Item], labels: list[int], existing: set[tuple[int, int]]) -> list[Edge]:
    """Weak same-size-bucket links (weight 0.15), only when n < 60 and only inside one cluster: consecutive-in-time
    members of the same (cluster, bucket), skipping pairs already linked spatially; capped at n edges."""
    n = len(items)
    if n >= SIZE_BUCKET_MAX_N:
        return []
    groups: dict[tuple[int, str], list[Item]] = defaultdict(list)
    for it in items:
        if it.size_bucket and labels[it.idx] >= 0:
            groups[(labels[it.idx], it.size_bucket)].append(it)
    out: set[tuple[int, int]] = set()
    for key in sorted(groups):
        chain = _order(groups[key])
        for x, y in zip(chain, chain[1:]):
            pair = (min(x.idx, y.idx), max(x.idx, y.idx))
            if pair not in existing:
                out.add(pair)
    return [("spatial", a, b, SIZE_BUCKET_WEIGHT) for a, b in sorted(out)[:n]]


def temporal_edges(items: list[Item], labels: list[int], window_hours: float) -> list[Edge]:
    """Directed earlier -> later: each item to the next item of the same ticker, and to the next item of the same
    cluster (not 'other'), when the gap is within the window. Weight = 1 - gap / window."""
    window = window_hours * 3600.0
    if window <= 0:
        return []
    best: dict[tuple[int, int], float] = {}

    def link_chain(chain: list[Item]):
        for x, y in zip(chain, chain[1:]):
            gap = (y.ts - x.ts).total_seconds()
            if gap > window:
                continue
            w = round(max(0.0, 1.0 - max(0.0, gap) / window), 6)
            key = (x.idx, y.idx)
            if w > best.get(key, -1.0):
                best[key] = w

    by_ticker: dict[str, list[Item]] = defaultdict(list)
    by_cluster: dict[int, list[Item]] = defaultdict(list)
    for it in items:
        for t in dict.fromkeys(it.tickers):
            by_ticker[t].append(it)
        if labels[it.idx] >= 0:
            by_cluster[labels[it.idx]].append(it)
    for t in sorted(by_ticker):
        link_chain(_order(by_ticker[t]))
    for c in sorted(by_cluster):
        link_chain(_order(by_cluster[c]))
    return [("temporal", a, b, w) for (a, b), w in sorted(best.items())]


TYPE_ORDER = {"contextual": 0, "spatial": 1, "temporal": 2}


def cap_edges(edges: list[Edge], cap: int) -> list[Edge]:
    """Keep at most `cap` edges. Each type gets a quota proportional to its share and keeps its strongest edges;
    any unused room goes to the strongest remaining edges overall. Output sorted (type, source, target)."""
    if len(edges) <= cap:
        return sorted(edges, key=lambda e: (TYPE_ORDER[e[0]], e[1], e[2]))
    by_type: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        by_type[e[0]].append(e)
    total = len(edges)
    keep: list[Edge] = []
    rest: list[Edge] = []
    for t in sorted(by_type, key=TYPE_ORDER.get):
        lst = sorted(by_type[t], key=lambda e: (-e[3], e[1], e[2]))
        quota = cap * len(lst) // total
        keep.extend(lst[:quota])
        rest.extend(lst[quota:])
    room = cap - len(keep)
    if room > 0:
        rest.sort(key=lambda e: (-e[3], TYPE_ORDER[e[0]], e[1], e[2]))
        keep.extend(rest[:room])
    return sorted(keep, key=lambda e: (TYPE_ORDER[e[0]], e[1], e[2]))
