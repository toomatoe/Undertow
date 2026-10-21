"""Text cleaning, tokenising and a small sparse TF-IDF (stdlib only, no numpy/sklearn).

Vectors are `dict[int, float]` (term index -> weight), L2-normalised. Term indices follow the sorted vocabulary,
so the same corpus always gives the same indices (deterministic).

TF-IDF choices (sklearn-compatible formulas):
- unigrams + bigrams; bigrams are built from the token sequence AFTER stopword removal (as sklearn does);
- sublinear tf: 1 + ln(count);
- smooth idf: ln((1 + n) / (1 + df)) + 1;
- min_df = 2 (1 when n < 10); max_df ratio 0.5, applied only when n >= 10 (on tiny corpora it would drop the
  very words that separate two topics).

Stopwords: English function words plus finance / SEC boilerplate that appears in almost every item and says
nothing about the event (entity suffixes such as inc/corp/ltd, 'form', 'filing', 'sec', 'edgar', 'exhibit',
'pursuant', 'registrant', 'company', 'announces', ...). Deliberately KEPT: event words such as 'shares',
'offering', 'warrants', 'priced', 'stock', 'notes', 'trial', 'merger', 'delisting', because they are exactly what
separates one cluster of filings from another.
"""

from __future__ import annotations

import html
import math
import re
from collections import Counter

_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_TOKEN = re.compile(r"[a-z0-9]+(?:['\-][a-z0-9]+)*")
_HAS_ALPHA = re.compile(r"[a-z]")

ENGLISH_STOPWORDS = frozenset("""
a about above after again against all almost also am an and any are aren't as at be because been before being
below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
either else ever every few for from further get gets got had hadn't has hasn't have haven't having he her here
hers herself him himself his how however i if in into is isn't it it's its itself just least less let let's like
made make many may me might more most much must my myself neither no nor not now of off often on once one only or
other others our ours ourselves out over own per put rather said same say says she should shouldn't since so some
such than that that's the their theirs them themselves then there there's these they this those though through
thus to too under until up upon us very via was wasn't we were weren't what when where whether which while who
whom whose why will with within without won't would wouldn't yet you your yours yourself yourselves
amid among across around new today year years week weeks day days month months time
""".split())

FINANCE_STOPWORDS = frozenset("""
inc inc. incorporated corp corporation co company companies ltd limited llc lp plc sa nv ag holdings holding group
form forms filing filings filed files file sec edgar exhibit exhibits item items pursuant registrant report reports
reported reporting statement statements current amendment amended announce announces announced announcement
release press reuters prnewswire newswire globe globenewswire businesswire accesswire wire update updates
nasdaq nyse amex otc ticker
accno size kb mb gb global 424b4 424b5 8-k 10-q 10-k
jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july august september
october november december monday tuesday wednesday thursday friday today
""".split())  # line 2+: EDGAR feed boilerplate ("Size: 744 KB AccNo: ...") and dates, which otherwise name clusters

STOPWORDS = ENGLISH_STOPWORDS | FINANCE_STOPWORDS


def clean(text: str | None) -> str:
    """Strip HTML tags, entities and URLs; lowercase."""
    if not text:
        return ""
    t = _TAG.sub(" ", text)
    t = html.unescape(t)
    t = _URL.sub(" ", t)
    return t.lower()


def tokenize(text: str | None) -> list[str]:
    """Content tokens in order: cleaned, stopwords / pure numbers / 1-char tokens removed."""
    out = []
    for tok in _TOKEN.findall(clean(text)):
        if len(tok) < 2 or tok in STOPWORDS or not _HAS_ALPHA.search(tok):
            continue
        out.append(tok)
    return out


def terms(text: str | None) -> list[str]:
    """Unigrams followed by bigrams of adjacent content tokens."""
    toks = tokenize(text)
    return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]


def l2_normalise(vec: dict[int, float]) -> dict[int, float]:
    norm = math.sqrt(sum(w * w for w in vec.values()))
    if norm <= 0:
        return {}
    return {k: w / norm for k, w in vec.items()}


def tfidf(
    docs: list[str], *, min_df: int | None = None, max_df: float = 0.5
) -> tuple[list[dict[int, float]], list[str], list[float], list[Counter]]:
    """Fit TF-IDF on `docs`.

    Returns (vectors, vocab, idf, term_counts): L2-normalised sparse vectors, the sorted vocabulary, idf per vocab
    index, and the raw in-vocabulary term counts per doc (used by c-TF-IDF naming).
    """
    n = len(docs)
    counts = [Counter(terms(d)) for d in docs]
    df: Counter = Counter()
    for c in counts:
        df.update(c.keys())
    if min_df is None:
        min_df = 1 if n < 10 else 2
    max_count = max_df * n if n >= 10 else float("inf")
    vocab = sorted(t for t, f in df.items() if f >= min_df and f <= max_count)
    index = {t: i for i, t in enumerate(vocab)}
    idf = [math.log((1 + n) / (1 + df[t])) + 1.0 for t in vocab]
    vectors: list[dict[int, float]] = []
    kept: list[Counter] = []
    for c in counts:
        vec = {}
        kc: Counter = Counter()
        for t, cnt in c.items():
            i = index.get(t)
            if i is None:
                continue
            vec[i] = (1.0 + math.log(cnt)) * idf[i]
            kc[t] = cnt
        vectors.append(l2_normalise(vec))
        kept.append(kc)
    return vectors, vocab, idf, kept
