# backend/app/graph: event graph engine

Builds a graph of recent SEC filings and news (`Article` rows) for a visual "what is happening together" view:
items are nodes, edges link items with similar wording, the same company, or close timing, and clusters group
related items under a short neutral name. Research and education only; content rules from frontend/AGENTS.md apply
(no buy/sell language, historical numbers labelled hypothetical).

**Edges are associations / proximity, not causes.** An edge says two items are similar, share a ticker or are close
in time; it never says one item led to another. Keep that wording in code, docstrings, `method` strings and the UI.

**Smoothing is GNN-style neighbourhood smoothing, not a trained GNN**: no learned weights, no training data.

Pure Python stdlib + existing deps (SQLAlchemy, anthropic SDK). **No numpy / sklearn / scipy / networkx / pandas**
(a test greps for them). **Never imports `app.main`**: main-specific things are parameters (`evidence_fn`, `namer`).

## Credits (University of Louisville, Long Nguyen's group)

- Hoang, Nguyen & Nguyen (tweet similarity graph + GNN embeddings to optimise event clustering, LLM-named
  clusters, per-tweet emotion), [arXiv 2408.11133](https://arxiv.org/abs/2408.11133). Adapted here: text similarity
  graph, neighbourhood smoothing of embeddings before clustering, optional LLM cluster names, per-cluster sentiment
  (from the existing `Article.sentiment`).
- Duong, Nguyen, Levin & Gary, CaST (contextual / spatial / temporal edges), [arXiv 2602.02601](https://arxiv.org/abs/2602.02601). Adapted here: the three
  edge families (contextual, spatial, temporal). "Spatial" here means same company / same size bucket, not geography.

## Files

| File | What |
|---|---|
| `__init__.py` | Exports `build_graph`, `GraphParams`, `clear_cache`, `EVIDENCE_NOTE`, `METHOD`, `OTHER_NAME` |
| `text.py` | `clean`, `tokenize`, `terms` (unigrams + bigrams), `STOPWORDS`, `tfidf` (sparse, L2-normalised) |
| `smooth.py` | `topk_neighbours` (cosine via inverted index), `smooth` (SGC/APPNP-like propagation), `cosine` |
| `edges.py` | `Item`, `contextual_edges`, `spatial_ticker_edges`, `size_bucket_edges`, `temporal_edges`, `cap_edges` |
| `cluster.py` | Deterministic weighted Louvain (`louvain`) |
| `naming.py` | c-TF-IDF terms (`ctfidf_terms`), `terms_name`, `clean_llm_name`, `is_neutral` (banned stems + claim words) |
| `timeline.py` | `build_timeline` (hour when days <= 3, else day; empty buckets included) |
| `llm.py` | Optional Claude namer `LLMNamer` (+ `default_namer(settings)`), cache `{data_dir}/graph_names.json` |
| `service.py` | `GraphParams`, `build_graph`: DB selection, orchestration, cluster stats, evidence, TTL cache |

## Pipeline (`service.build_graph`)

1. **Selection**: `published_at` in `[now - days, now]`; `source` = `filings` (`source == 'edgar'`), `news`
   (`source != 'edgar'`) or `all`; optional `ticker` (via `ArticleTicker.symbol`, uppercased). Ordered by severity
   desc (nulls last), then `published_at` desc, keep `max_nodes` (signal filings first so news does not drown them);
   `params.truncated` / `params.total_in_window` report the cut. Nodes are then processed in `Article.id` order.
   Size bucket = `Company.size_bucket` of the node's first ticker (tickers sorted alphabetically).
   Text = `title + ' ' + (ai_summary or snippet or '')`, HTML/URLs stripped, lowercased. `body` is never used.
2. **Embeddings** (`text.tfidf`): unigrams + bigrams (bigrams after stopword removal), sublinear tf, smooth idf
   `ln((1+n)/(1+df))+1`, min_df 2 (1 when n < 10), max_df ratio 0.5 (only when n >= 10), sparse `dict[int,float]`,
   unit L2. Stopwords = English + SEC boilerplate (entity suffixes inc/corp/ltd, form, filing, sec, edgar, exhibit,
   item, pursuant, registrant, company, announces, newswire names, exchange names). Event words such as `shares`,
   `offering`, `warrants`, `priced`, `stock`, `trial` are **kept**: they are what separates clusters.
3. **Similarity**: top-k (8) neighbours per node with cosine > `min_sim` (0.05), dot products accumulated only for
   docs sharing a term (term -> postings). Ties broken by smaller index.
4. **Smoothing** (not a trained GNN): `h(t+1) = normalise(alpha*x + (1-alpha) * sim-weighted mean of neighbours' h(t))`
   over the fixed raw top-k graph, `hops` = 2 (0-2), alpha 0.5. Each smoothed vector keeps its 48 largest entries
   (weights < 1e-3 dropped) and is re-normalised, to bound density. Top-k is recomputed on the smoothed vectors.
5. **Edges** (`{source, target, type, weight 0..1}`):
   - `contextual`: **smoothed** cosine >= 0.2, union of each node's top-k, undirected (`source < target`, deduped).
   - `spatial`: same ticker, weight 1.0, consecutive-in-time items per ticker (chain, not clique); plus weak
     same-size-bucket links (0.15) only when n < 60, only between members of the same cluster (added after
     clustering, display only), consecutive in time, skipping pairs already linked, capped at n.
   - `temporal`: directed earlier -> later; each item to the next item of the same ticker and to the next item of
     the same cluster (not 'other') within 48 h; weight `1 - gap/window`.
   - Total capped at `8 * n`: each type keeps its strongest edges within a quota proportional to its share, spare
     room goes to the strongest remaining edges.
6. **Clustering**: deterministic Louvain over contextual + same-ticker spatial edges (nodes in id order, a node moves
   only for a strictly better gain, ties -> smallest community label, communities renumbered by smallest member each
   level). Groups < 3 items -> cluster `-1` ("Other / unclustered"). Clusters renumbered `0..k-1` by size desc, then
   earliest start, then smallest member.
7. **Naming** (`name_source='terms'`): top 3 c-TF-IDF terms (BERTopic: `tf(t,c) * log(1 + A / f(t))`, A = average
   term occurrences per cluster, f(t) = occurrences over all clusters incl. 'other'; redundant terms whose words are
   inside an already chosen term are skipped; non-neutral terms dropped) joined ` / `, then the most common signal
   label (`signal_def(code).label`), then the top 2 tickers, joined with ` · `, e.g.
   `offering / warrants / priced · Offering priced (424B) · OF0, OF1`.
   Optional namer (`name_source='llm'`): the injected `namer`, else `llm.default_namer(settings)` which exists only
   when `ANTHROPIC_API_KEY` is set (`settings.enrich_enabled`), model `settings.enrich_model`, called like
   `pipeline/enrich.py`. Only the 12 largest clusters are sent. Output is validated by `clean_llm_name` (non-empty,
   <= 60 chars, neutral); any failure or invalid name falls back to the terms name. LLM names are cached by sha256 of
   (sorted member ids, terms) in `{data_dir}/graph_names.json` (atomic write, bounded at 2000 entries).
8. **Cluster stats**: `tickers` top 5 by count, `signal_mix` desc, `mean_sentiment` (non-null `Article.sentiment`,
   4 dp) + `sentiment_n`, `start`/`end`, `evidence` = `evidence_fn(dominant signal, dominant size bucket)` (default
   `app.vault.make_evidence_fn(settings.data_dir)`: main-study 20-day rows, forward-test row for forward-test codes)
   as a plain dict (EvidenceOut fields) or null; always null for the 'other' group. `evidence_note` =
   `EVIDENCE_NOTE` ("Historical event-study result (hypothetical, gross of real-world frictions); not a forecast.").
9. **Timeline**: `granularity` hour when days <= 3 else day; buckets from floor(now - days) to floor(now), empty ones
   included, `counts` only nonzero keys (`str(cluster id)`, `-1` included); counts sum to the node count.
10. **Cache**: module-level `OrderedDict`, key `(GraphParams, max Article.id in window, enrich_enabled, explicit now, id(evidence_fn))`,
    TTL 300 s (`_clock`, monkeypatchable), max 16 entries, under a lock. An injected `evidence_fn` is cached by identity
    (main.py passes the module-level `vault_evidence`); an injected `namer` bypasses the cache. A cached dict is shared: callers must not mutate it.

## Public API and contract

```python
from app.graph import GraphParams, build_graph, clear_cache

params = GraphParams(days=7, max_nodes=400, ticker=None, source="all")  # ValueError on bad input
# days 1-30, max_nodes 20-1000 (default 400), source all|filings|news, ticker ^[A-Z0-9.\-]{1,12}$ (uppercased)
graph = build_graph(session, params, now=None, evidence_fn=None, namer=None, use_cache=True)
```

Returns a plain dict (datetimes are aware UTC `datetime` objects; the API item builds Pydantic models from it):

```
{ nodes:[{id, kind:'filing'|'news', title, url, source_name, form|null, ticker|null (first), tickers:[str],
          signals:[codes, most severe first], signal_labels:[str], severity|null, size_bucket|null, sentiment|null,
          published_at, cluster:int (-1 = other), x:null, y:null}],          # id order
  edges:[{source:int, target:int, type:'contextual'|'spatial'|'temporal', weight:float}],
  clusters:[{id, name, name_source:'terms'|'llm', terms:[str], size, tickers:[str], signal_mix:[{code,label,count}],
             mean_sentiment|null, sentiment_n, start, end, evidence:dict|null, evidence_note}],
             # size desc; 'Other / unclustered' (id -1) last when non-empty
  timeline:{granularity:'hour'|'day', buckets:[{t, counts:{str:int}}]},
  params:{days, max_nodes, ticker|null, source, truncated, total_in_window},
  generated_at, method:{embedding, smoothing, clustering, edges, naming, note} }
```

`method.note` states that edges are associations / proximity, not causes, and credits both papers.

## Invariants

- No heavy deps; stdlib + SQLAlchemy only (anthropic only inside `llm.py`, lazily). Do not touch requirements.
- Deterministic: same rows -> same output regardless of insertion order (sorted vocab, id-ordered nodes, explicit
  tie-breaks everywhere). Tests compare whole outputs across runs and shuffled inserts.
- No wording that presents an edge or cluster as one event producing another; no buy/sell/target/profit stems in
  names (`naming.is_neutral`, reusing `newsletter.service.BANNED`).
- LLM naming optional, cached under `DATA_DIR`, never in tests (tests pass fake namers / fake clients and patch
  `LLMNamer._ask` to fail).
- Never imports `app.main`; SQLite- and Postgres-compatible queries only.
- Performance: 400 nodes ~0.2 s in the `undertow-api-test` image (measured 0.16-0.20 s on synthetic docs; the test
  allows 5 s).

## How to test

```bash
bash scripts/pytest.sh tests/test_graph.py
```

`tests/test_graph.py`: hand-computed TF-IDF, tokenizer/stopwords, min_df/max_df, top-k + smoothing norms, topic
separation and determinism, Louvain order independence, small groups -> -1, edge types/direction/dedupe/window/cap,
c-TF-IDF naming, fake/failing/non-neutral namers, no LLM without a key, LLM cache file with a fake client, evidence
injection, timeline, filters + truncation, params validation, contract shape and wording, empty window, cache
TTL/invalidation, 400-node timing, package hygiene greps.
