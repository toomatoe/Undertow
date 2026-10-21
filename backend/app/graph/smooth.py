"""Cosine top-k neighbours (inverted index) and GNN-style neighbourhood smoothing.

This is GNN-style neighbourhood smoothing, NOT a trained GNN: there are no learned weights. It follows the
simplified-graph-convolution idea (SGC / APPNP propagation) used to make text embeddings cluster better in
Hoang, Nguyen & Nguyen (arXiv 2408.11133):

    h0 = x
    h(t+1) = normalise( alpha * x + (1 - alpha) * sum_j w_ij h(t)_j / sum_j w_ij )

over the fixed top-k cosine graph of the raw TF-IDF vectors (w_ij = raw cosine). A node without neighbours keeps
x. Each smoothed vector keeps only its `max_terms` largest entries (and drops weights below `min_weight`) before
re-normalising to unit L2, which bounds density so the second similarity pass stays fast.
"""

from __future__ import annotations

import heapq
from collections import defaultdict

from app.graph.text import l2_normalise

Neighbours = list[list[tuple[int, float]]]


def topk_neighbours(vectors: list[dict[int, float]], k: int = 8, min_sim: float = 0.0) -> Neighbours:
    """For each doc, its k most cosine-similar other docs with sim > min_sim, sorted (sim desc, index asc).

    Vectors must be L2-normalised (cosine = dot product). Dot products are accumulated only for docs that share
    at least one term, via term -> postings lists.
    """
    postings: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for d, vec in enumerate(vectors):
        for t, w in vec.items():
            postings[t].append((d, w))
    out: Neighbours = []
    for i, vec in enumerate(vectors):
        acc: dict[int, float] = defaultdict(float)
        for t, w in vec.items():
            for j, wj in postings[t]:
                if j != i:
                    acc[j] += w * wj
        cands = [(s, j) for j, s in acc.items() if s > min_sim]
        best = heapq.nsmallest(k, cands, key=lambda p: (-p[0], p[1]))
        out.append([(j, min(1.0, s)) for s, j in best])
    return out


def smooth(
    vectors: list[dict[int, float]],
    neighbours: Neighbours,
    *,
    alpha: float = 0.5,
    hops: int = 2,
    max_terms: int = 48,
    min_weight: float = 1e-3,
) -> list[dict[int, float]]:
    """`hops` rounds of similarity-weighted neighbour averaging (0 = return the input). Output is unit L2."""
    if hops <= 0:
        return [dict(v) for v in vectors]
    h = vectors
    for _ in range(hops):
        nxt = []
        for i, x in enumerate(vectors):
            nb = neighbours[i]
            total = sum(w for _, w in nb)
            if not nb or total <= 0:
                nxt.append(dict(x))
                continue
            acc: dict[int, float] = defaultdict(float)
            for t, v in x.items():
                acc[t] += alpha * v
            scale = (1.0 - alpha) / total
            for j, w in nb:
                f = w * scale
                for t, v in h[j].items():
                    acc[t] += f * v
            items = [(t, v) for t, v in acc.items() if v >= min_weight]
            if len(items) > max_terms:
                items = heapq.nsmallest(max_terms, items, key=lambda p: (-p[1], p[0]))
            nxt.append(l2_normalise(dict(items)))
        h = nxt
    return h


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())
