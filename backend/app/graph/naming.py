"""Cluster names from class-based TF-IDF (c-TF-IDF, as in BERTopic) plus signal label and tickers.

c-TF-IDF weight of term t in cluster c:  tf(t, c) * log(1 + A / f(t))
  tf(t, c) = count of t over the cluster's items, f(t) = count of t over all clusters (including 'other'),
  A = average number of term occurrences per cluster (BERTopic's definition; it keeps A and f(t) in the same unit).

Names must stay neutral: terms matching the newsletter's banned-word stems (buy/sell/target/profit/...) or words
that read as a claim about why something happened are never used in a name.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.newsletter.service import BANNED

# Words that would turn a descriptive name into a claim of one event producing another.
_CLAIM_WORDS = re.compile(r"\b(caus\w*|because|due|trigger\w*|led|leads?|drives?|driven|impact\w*)\b", re.I)

NAME_MAX = 60


def is_neutral(text: str) -> bool:
    return not BANNED.search(text) and not _CLAIM_WORDS.search(text)


def ctfidf_terms(cluster_counts: dict[int, Counter], top: int = 3) -> dict[int, list[str]]:
    """Top distinctive terms per cluster. `cluster_counts` maps cluster id -> term Counter (may include -1)."""
    if not cluster_counts:
        return {}
    f: Counter = Counter()
    for c in cluster_counts.values():
        f.update(c)
    A = sum(sum(c.values()) for c in cluster_counts.values()) / len(cluster_counts)
    out: dict[int, list[str]] = {}
    for cid, counts in cluster_counts.items():
        scored = sorted(
            ((tf * math.log(1.0 + A / f[t]), t) for t, tf in counts.items() if is_neutral(t)),
            key=lambda p: (-p[0], p[1]),
        )
        chosen: list[str] = []
        chosen_words: list[set[str]] = []
        for _, t in scored:
            words = set(t.split())
            # skip a term that adds nothing (its words are inside a chosen term, or a chosen term is inside it)
            if any(words <= cw or cw <= words for cw in chosen_words):
                continue
            chosen.append(t)
            chosen_words.append(words)
            if len(chosen) >= top:
                break
        out[cid] = chosen
    return out


def terms_name(cid: int, terms: list[str], signal_label: str | None, tickers: list[str]) -> str:
    parts = []
    if terms:
        parts.append(" / ".join(terms))
    if signal_label:
        parts.append(signal_label)
    if tickers:
        parts.append(", ".join(tickers[:2]))
    return " · ".join(parts) if parts else f"Cluster {cid + 1}"


def clean_llm_name(name) -> str | None:
    """Validate a namer's output: a non-empty neutral string, trimmed to NAME_MAX chars; else None."""
    if not isinstance(name, str):
        return None
    name = " ".join(name.strip().strip('"\'').split())
    if not name:
        return None
    if len(name) > NAME_MAX:
        name = name[: NAME_MAX - 1].rstrip() + "…"
    return name if is_neutral(name) else None
