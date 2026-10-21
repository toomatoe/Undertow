"""Event graph: DB selection, orchestration, cluster stats and a small TTL cache.

Pipeline (details in AGENTS.md): select Article rows in the window -> TF-IDF -> raw top-k cosine graph ->
GNN-style neighbourhood smoothing (not a trained GNN) -> smoothed top-k graph -> contextual + same-ticker spatial
edges -> deterministic Louvain -> clusters < 3 items become 'other' (-1) -> size-bucket and temporal edges -> edge
cap -> c-TF-IDF names (optional Claude names) -> cluster stats + historical evidence -> timeline.

Edges are associations / proximity only (similar wording, same company, close in time), never a claim that one
item led to another. Never imports app.main.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.graph import cluster as clustering
from app.graph import edges as edge_mod
from app.graph.naming import clean_llm_name, ctfidf_terms, terms_name
from app.graph.smooth import smooth, topk_neighbours
from app.graph.text import tfidf
from app.graph.timeline import build_timeline
from app.models import Article, ArticleTicker, Company
from app.pipeline.signals import signal_def

log = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")
SOURCES = ("all", "filings", "news")
DAYS_MIN, DAYS_MAX = 1, 30
NODES_MIN, NODES_MAX = 20, 1000
MIN_CLUSTER_SIZE = 3
EDGES_PER_NODE_CAP = 8
MAX_LLM_CLUSTERS = 12  # only the largest clusters are sent to the optional namer
OTHER_ID = -1
OTHER_NAME = "Other / unclustered"
EVIDENCE_NOTE = "Historical event-study result (hypothetical, gross of real-world frictions); not a forecast."

CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 16
_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()
_clock = time.monotonic

METHOD = {
    "embedding": "TF-IDF (unigrams + bigrams, sublinear tf, smooth idf, English + SEC-boilerplate stopwords), "
                 "sparse and L2-normalised",
    "smoothing": "GNN-style neighbourhood smoothing over the top-k cosine graph (SGC/APPNP-like propagation, "
                 "alpha-weighted, up to 2 hops); not a trained GNN",
    "clustering": "Deterministic Louvain (modularity) over contextual + same-ticker edges; groups under 3 items "
                  "are shown as 'Other / unclustered'",
    "edges": "contextual = cosine of smoothed vectors above a threshold (top-k per item); spatial = same ticker "
             "(consecutive in time) plus weak same-size-bucket links on small graphs; temporal = next item of the "
             "same ticker or cluster within the window, earlier to later",
    "naming": "c-TF-IDF distinctive terms + most common signal + top tickers; optional short Claude name when an "
              "API key is configured",
    "note": "Edges show associations and proximity (similar wording, same company, close in time), not causes. "
            "Adapted from University of Louisville research: Hoang, Nguyen & Nguyen, arXiv 2408.11133 (similarity "
            "graph + GNN embeddings for event clustering, LLM-named clusters) and Duong, Nguyen, Levin & Gary, "
            "CaST, arXiv 2602.02601 (contextual, spatial and temporal edges).",
}

Namer = Callable[[dict], "str | None"]
EvidenceFn = Callable[[str, str], object]


@dataclass(frozen=True)
class GraphParams:
    days: int = 7
    max_nodes: int = 400
    ticker: str | None = None
    source: str = "all"
    # tuning (not exposed by the API)
    k: int = 8
    min_sim: float = 0.05
    contextual_threshold: float = 0.2
    alpha: float = 0.5
    hops: int = 2
    temporal_window_hours: float = 48.0

    def __post_init__(self):
        if self.ticker is not None:
            t = self.ticker.strip().upper() or None
            object.__setattr__(self, "ticker", t)
        object.__setattr__(self, "source", (self.source or "all").strip().lower())
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.days, int) or not DAYS_MIN <= self.days <= DAYS_MAX:
            raise ValueError(f"days must be an integer {DAYS_MIN}-{DAYS_MAX}")
        if not isinstance(self.max_nodes, int) or not NODES_MIN <= self.max_nodes <= NODES_MAX:
            raise ValueError(f"max_nodes must be an integer {NODES_MIN}-{NODES_MAX}")
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}")
        if self.ticker is not None and not TICKER_RE.match(self.ticker):
            raise ValueError("ticker must match ^[A-Z0-9.\\-]{1,12}$")
        if not 0 <= self.hops <= 2:
            raise ValueError("hops must be 0-2")
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError("alpha must be 0-1")
        if self.k < 1:
            raise ValueError("k must be >= 1")


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _filters(params: GraphParams, since: datetime, now: datetime) -> list:
    conds = [Article.published_at >= since, Article.published_at <= now]
    if params.source == "filings":
        conds.append(Article.source == "edgar")
    elif params.source == "news":
        conds.append(Article.source != "edgar")
    if params.ticker:
        conds.append(Article.id.in_(select(ArticleTicker.article_id).where(ArticleTicker.symbol == params.ticker)))
    return conds


def _evidence_row(evidence_fn: EvidenceFn | None, code: str | None, bucket: str | None) -> dict | None:
    if evidence_fn is None or not code or not bucket:
        return None
    try:
        row = evidence_fn(code, bucket)
    except Exception as exc:
        log.warning("Evidence lookup failed for %s/%s: %s", code, bucket, exc)
        return None
    if row is None:
        return None
    if hasattr(row, "model_dump"):
        row = row.model_dump()
    return dict(row) if isinstance(row, dict) else None


def _label(code: str) -> str:
    sd = signal_def(code)
    return sd.label if sd else code


def build_graph(
    session: Session,
    params: GraphParams,
    *,
    now: datetime | None = None,
    evidence_fn: EvidenceFn | None = None,
    namer: Namer | None = None,
    use_cache: bool = True,
) -> dict:
    """Build the event graph dict (contract in AGENTS.md).

    Defaults: evidence_fn = app.vault.make_evidence_fn(settings.data_dir); namer = the Claude namer only when
    ANTHROPIC_API_KEY is set. The cache is used only with the default evidence_fn/namer; a cached dict is shared
    between callers and must not be mutated.
    """
    from app.config import get_settings

    settings = get_settings()
    explicit_now = now is not None
    now = _aware(now) if now is not None else datetime.now(timezone.utc)
    since = now - timedelta(days=params.days)
    conds = _filters(params, since, now)

    # A caller-supplied evidence_fn is cached by identity (main.py passes the module-level vault_evidence);
    # a caller-supplied namer disables the cache (tests inject fakes).
    cacheable = use_cache and namer is None
    key = None
    if cacheable:
        max_id = session.scalar(select(func.max(Article.id)).where(*conds))
        key = (params, max_id, bool(settings.enrich_enabled), now if explicit_now else None,
               id(evidence_fn) if evidence_fn is not None else None)
        with _cache_lock:
            hit = _cache.get(key)
            if hit and _clock() - hit[0] < CACHE_TTL_SECONDS:
                _cache.move_to_end(key)
                return hit[1]

    if evidence_fn is None:
        from app.vault import make_evidence_fn

        evidence_fn = make_evidence_fn(settings.data_dir)
    if namer is None:
        from app.graph.llm import default_namer

        namer = default_namer(settings)

    result = _build(session, params, now, since, conds, evidence_fn, namer)

    if cacheable:
        with _cache_lock:
            _cache[key] = (_clock(), result)
            _cache.move_to_end(key)
            while len(_cache) > CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)
    return result


DOMINANT_SIGNAL_SHARE = 0.3  # share of a cluster a signal must cover to name it and supply its evidence
NEWS_SHARE = 0.4  # with source=all, up to this share of max_nodes is reserved for news (filings fill the rest)


def _select_rows(session, params: GraphParams, conds) -> list:
    """Signal filings first (severity desc, then newest); with source=all, news gets up to NEWS_SHARE of the cap so
    the graph shows filings in their news context instead of filings only. Unused share goes to the other side."""
    by_severity = (Article.severity.is_(None), Article.severity.desc(), Article.published_at.desc(), Article.id.desc())
    if params.source != "all":
        return list(session.scalars(select(Article).where(*conds).order_by(*by_severity).limit(params.max_nodes)))
    news_cap = int(params.max_nodes * NEWS_SHARE)
    news = list(session.scalars(select(Article).where(*conds, Article.source != "edgar")
                                .order_by(Article.published_at.desc(), Article.id.desc()).limit(news_cap)))
    filings = list(session.scalars(select(Article).where(*conds, Article.source == "edgar")
                                   .order_by(*by_severity).limit(params.max_nodes - len(news))))
    if len(news) + len(filings) < params.max_nodes and len(news) == news_cap:
        seen = {a.id for a in news}
        more = session.scalars(select(Article).where(*conds, Article.source != "edgar")
                               .order_by(Article.published_at.desc(), Article.id.desc())
                               .limit(params.max_nodes - len(filings)))
        news = [a for a in more if a.id not in seen][: params.max_nodes - len(filings) - len(news)] + news
    return news + filings


def _build(session, params: GraphParams, now, since, conds, evidence_fn, namer) -> dict:
    total = session.scalar(select(func.count(Article.id)).where(*conds)) or 0
    rows = _select_rows(session, params, conds)
    rows.sort(key=lambda a: a.id)
    n = len(rows)

    tickers_of = [sorted({t.symbol.upper() for t in a.tickers}) for a in rows]
    first = {ts[0] for ts in tickers_of if ts}
    buckets: dict[str, str | None] = {}
    if first:
        for sym, b in session.execute(select(Company.symbol, Company.size_bucket).where(Company.symbol.in_(first))):
            buckets[sym] = b

    items: list[edge_mod.Item] = []
    texts: list[str] = []
    for i, a in enumerate(rows):
        ts = _aware(a.published_at)
        tks = tickers_of[i]
        items.append(edge_mod.Item(i, ts, tks, buckets.get(tks[0]) if tks else None))
        texts.append(f"{a.title or ''} {a.ai_summary or a.snippet or ''}")

    # --- embeddings, smoothing, contextual graph -------------------------------------------------
    labels = [OTHER_ID] * n
    edges: list[edge_mod.Edge] = []
    counts: list[Counter] = [Counter() for _ in range(n)]
    if n:
        vectors, _vocab, _idf, counts = tfidf(texts)
        raw_nb = topk_neighbours(vectors, params.k, params.min_sim)
        if params.hops > 0:
            h = smooth(vectors, raw_nb, alpha=params.alpha, hops=params.hops)
            nb = topk_neighbours(h, params.k, params.min_sim)
        else:
            nb = raw_nb
        contextual = edge_mod.contextual_edges(nb, params.contextual_threshold)
        spatial = edge_mod.spatial_ticker_edges(items)

        raw = clustering.louvain(n, [(a, b, w) for _, a, b, w in contextual + spatial])
        groups: dict[int, list[int]] = defaultdict(list)
        for i, c in enumerate(raw):
            groups[c].append(i)
        kept = [m for m in groups.values() if len(m) >= MIN_CLUSTER_SIZE]
        kept.sort(key=lambda m: (-len(m), min(items[i].ts for i in m), min(m)))
        for cid, members in enumerate(kept):
            for i in members:
                labels[i] = cid

        existing = {(a, b) for _, a, b, _ in spatial}
        bucket_edges = edge_mod.size_bucket_edges(items, labels, existing)
        temporal = edge_mod.temporal_edges(items, labels, params.temporal_window_hours)
        edges = edge_mod.cap_edges(contextual + spatial + bucket_edges + temporal, EDGES_PER_NODE_CAP * n)

    # --- nodes -----------------------------------------------------------------------------------
    nodes = []
    for i, a in enumerate(rows):
        codes = list(a.signals or [])
        nodes.append({
            "id": a.id,
            "kind": "filing" if a.source == "edgar" else "news",
            "title": a.title or "",
            "url": a.url or "",
            "source_name": a.source_name or "",
            "form": a.form,
            "ticker": tickers_of[i][0] if tickers_of[i] else None,
            "tickers": tickers_of[i],
            "signals": codes,
            "signal_labels": [_label(c) for c in codes],
            "severity": a.severity,
            "size_bucket": items[i].size_bucket,
            "sentiment": a.sentiment,
            "published_at": items[i].ts,
            "cluster": labels[i],
            "x": None,
            "y": None,
        })

    # --- clusters --------------------------------------------------------------------------------
    members_of: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(labels):
        members_of[c].append(i)
    cluster_counts = {c: sum((counts[i] for i in m), Counter()) for c, m in members_of.items()}
    top_terms = ctfidf_terms(cluster_counts)
    real_ids = sorted(c for c in members_of if c != OTHER_ID)

    clusters = []
    for cid in real_ids + ([OTHER_ID] if OTHER_ID in members_of else []):
        m = members_of[cid]
        sig = Counter(code for i in m for code in (rows[i].signals or []))
        signal_mix = [{"code": c, "label": _label(c), "count": k}
                      for c, k in sorted(sig.items(), key=lambda p: (-p[1], p[0]))]
        tick = Counter(t for i in m for t in tickers_of[i])
        top_tickers = [t for t, _ in sorted(tick.items(), key=lambda p: (-p[1], p[0]))[:5]]
        sents = [rows[i].sentiment for i in m if rows[i].sentiment is not None]
        bucket_count = Counter(items[i].size_bucket for i in m if items[i].size_bucket)
        dom_bucket = sorted(bucket_count.items(), key=lambda p: (-p[1], p[0]))[0][0] if bucket_count else None
        # A signal names the cluster (and picks its evidence row) only if it covers a real share of it: a 67-item
        # news cluster with 2 offering filings is not an "offering" cluster.
        dominant = signal_mix[0] if signal_mix and signal_mix[0]["count"] >= max(2, DOMINANT_SIGNAL_SHARE * len(m)) else None
        dom_signal = dominant["code"] if dominant else None
        dom_label = dominant["label"] if dominant else None
        terms = top_terms.get(cid, [])
        if cid == OTHER_ID:
            name, source, evidence = OTHER_NAME, "terms", None
        else:
            name = terms_name(cid, terms, dom_label, top_tickers)
            source = "terms"
            if namer is not None and cid < MAX_LLM_CLUSTERS:
                info = {
                    "id": cid,
                    "member_ids": [rows[i].id for i in m],
                    "terms": terms,
                    "titles": [rows[i].title for i in sorted(m, key=lambda i: (items[i].ts, i))][:12],
                    "tickers": top_tickers,
                    "signal_label": dom_label,
                }
                try:
                    llm_name = clean_llm_name(namer(info))
                except Exception as exc:
                    log.warning("Cluster namer failed: %s", exc)
                    llm_name = None
                if llm_name:
                    name, source = llm_name, "llm"
            evidence = _evidence_row(evidence_fn, dom_signal, dom_bucket)
        clusters.append({
            "id": cid,
            "name": name,
            "name_source": source,
            "terms": terms,
            "size": len(m),
            "tickers": top_tickers,
            "signal_mix": signal_mix,
            "mean_sentiment": round(sum(sents) / len(sents), 4) if sents else None,
            "sentiment_n": len(sents),
            "start": min(items[i].ts for i in m),
            "end": max(items[i].ts for i in m),
            "evidence": evidence,
            "evidence_note": EVIDENCE_NOTE,
        })

    return {
        "nodes": nodes,
        "edges": [{"source": rows[a].id, "target": rows[b].id, "type": t, "weight": float(w)} for t, a, b, w in edges],
        "clusters": clusters,
        "timeline": build_timeline(since, now, params.days, [(items[i].ts, labels[i]) for i in range(n)]),
        "params": {
            "days": params.days,
            "max_nodes": params.max_nodes,
            "ticker": params.ticker,
            "source": params.source,
            "truncated": total > n,
            "total_in_window": int(total),
        },
        "generated_at": now,
        "method": dict(METHOD),
    }
