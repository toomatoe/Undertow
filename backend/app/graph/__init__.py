"""Event graph of filings and news (pure Python): TF-IDF, GNN-style neighbourhood smoothing (not a trained GNN),
contextual / spatial / temporal association edges, deterministic Louvain clusters, c-TF-IDF names.

See AGENTS.md in this folder. Never imports app.main.
"""

from app.graph.service import (
    EVIDENCE_NOTE,
    METHOD,
    OTHER_NAME,
    GraphParams,
    build_graph,
    clear_cache,
)

__all__ = ["EVIDENCE_NOTE", "METHOD", "OTHER_NAME", "GraphParams", "build_graph", "clear_cache"]
