"""Deterministic Louvain community detection (modularity, weighted, undirected) in pure Python.

Nodes are 0..n-1 and are always visited in index order (the engine sorts nodes by Article.id first). A node moves
only to a community with a strictly better modularity gain; ties between candidate communities go to the smallest
label. Communities are renumbered by their smallest member before each aggregation level, so the result does not
depend on edge insertion order.
"""

from __future__ import annotations

from collections import defaultdict

EPS = 1e-12


def _local_moving(adj: list[dict[int, float]], self_w: list[float], resolution: float, max_passes: int):
    n = len(adj)
    k = [sum(adj[i].values()) + 2.0 * self_w[i] for i in range(n)]
    m2 = sum(k)
    comm = list(range(n))
    if m2 <= 0:
        return comm, False
    tot = list(k)
    moved_any = False
    for _ in range(max_passes):
        moved = False
        for i in range(n):
            ci = comm[i]
            tot[ci] -= k[i]
            links: dict[int, float] = defaultdict(float)
            for j, w in adj[i].items():
                links[comm[j]] += w
            def gain(c: int) -> float:
                return links.get(c, 0.0) - resolution * tot[c] * k[i] / m2
            best, best_gain = ci, gain(ci)
            for c in sorted(links):
                g = gain(c)
                if g > best_gain + EPS:
                    best, best_gain = c, g
            tot[best] += k[i]
            if best != ci:
                comm[i] = best
                moved = True
                moved_any = True
        if not moved:
            break
    return comm, moved_any


def louvain(
    n: int, edges: list[tuple[int, int, float]], *, resolution: float = 1.0, max_levels: int = 10, max_passes: int = 50
) -> list[int]:
    """Community label per node (labels are arbitrary ints; equal label = same community)."""
    adj: list[dict[int, float]] = [defaultdict(float) for _ in range(n)]
    self_w = [0.0] * n
    for a, b, w in sorted(edges):
        if w <= 0:
            continue
        if a == b:
            self_w[a] += w
        else:
            adj[a][b] += w
            adj[b][a] += w
    membership = list(range(n))
    for _ in range(max_levels):
        comm, moved = _local_moving(adj, self_w, resolution, max_passes)
        if not moved:
            break
        # renumber by smallest member (members are visited in index order)
        remap: dict[int, int] = {}
        for c in comm:
            if c not in remap:
                remap[c] = len(remap)
        comm = [remap[c] for c in comm]
        membership = [comm[c] for c in membership]
        size = len(remap)
        new_adj: list[dict[int, float]] = [defaultdict(float) for _ in range(size)]
        new_self = [0.0] * size
        for i in range(len(adj)):
            ci = comm[i]
            new_self[ci] += self_w[i]
            for j, w in adj[i].items():
                cj = comm[j]
                if ci == cj:
                    if i < j:
                        new_self[ci] += w
                else:
                    new_adj[ci][cj] += w
        adj, self_w = new_adj, new_self
        if size == 1:
            break
    return membership
