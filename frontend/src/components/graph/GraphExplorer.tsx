"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { api, type GraphEdgeType, type GraphResponse, type GraphSource } from "@/lib/api";

import ClusterLegend from "./ClusterLegend";
import GraphCanvas from "./GraphCanvas";
import styles from "./graph.module.css";
import HowItWorks from "./HowItWorks";
import NodeDetail from "./NodeDetail";
import TimeScrubber, { SCRUB_STEPS } from "./TimeScrubber";
import { buildColorIndex, EDGE_BORDER, EDGE_LABELS, EDGE_TYPES, normaliseTicker, OTHER_CLUSTER, TICKER_RE } from "./util";

const DAY_OPTIONS = [1, 3, 7, 14, 30];
const MAX_OPTIONS = [200, 400, 700, 1000];
const SOURCES: { value: GraphSource; label: string }[] = [
  { value: "all", label: "Filings and news" },
  { value: "filings", label: "Filings only" },
  { value: "news", label: "News only" },
];
const DEFAULTS = { days: 7, source: "all" as GraphSource, ticker: "", maxNodes: 400 };
const PLAY_MS = 12000; // full replay of the window

interface Query {
  days: number;
  source: GraphSource;
  ticker: string;
  maxNodes: number;
}

function intIn(raw: string | null, lo: number, hi: number, fallback: number): number {
  const v = raw === null ? NaN : Number(raw);
  return Number.isInteger(v) && v >= lo && v <= hi ? v : fallback;
}

function parseQuery(sp: URLSearchParams | null): Query {
  const src = sp?.get("source");
  const ticker = normaliseTicker(sp?.get("ticker"));
  return {
    days: intIn(sp?.get("days") ?? null, 1, 30, DEFAULTS.days),
    source: src === "filings" || src === "news" || src === "all" ? src : DEFAULTS.source,
    ticker: TICKER_RE.test(ticker) ? ticker : "",
    maxNodes: intIn(sp?.get("max_nodes") ?? null, 20, 1000, DEFAULTS.maxNodes),
  };
}

function toSearch(q: Query): string {
  const qs = new URLSearchParams();
  if (q.ticker) qs.set("ticker", q.ticker);
  if (q.days !== DEFAULTS.days) qs.set("days", String(q.days));
  if (q.source !== DEFAULTS.source) qs.set("source", q.source);
  if (q.maxNodes !== DEFAULTS.maxNodes) qs.set("max_nodes", String(q.maxNodes));
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export function GraphSkeleton() {
  return (
    <div className={styles.root} aria-busy="true">
      <div className="skel skel-line" style={{ width: "60%" }} />
      <div className={`skel ${styles.skeleton}`} />
      <div className="skel skel-block" />
    </div>
  );
}

/** /graph body: controls (synced to the URL), canvas graph, time scrubber, detail panel, cluster legend, method note. */
export default function GraphExplorer() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [q, setQ] = useState<Query>(() => parseQuery(searchParams));
  const [tickerInput, setTickerInput] = useState(q.ticker);
  const [tickerError, setTickerError] = useState<string | null>(null);
  const [data, setData] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [scrub, setScrub] = useState(SCRUB_STEPS);
  const [playing, setPlaying] = useState(false);
  const scrubRef = useRef(scrub);
  useEffect(() => {
    scrubRef.current = scrub; // read by the play loop (declared before it, so it runs first in a commit)
  }, [scrub]);
  const [edgeTypes, setEdgeTypes] = useState<Record<GraphEdgeType, boolean>>({ contextual: true, spatial: true, temporal: true });
  const [highlight, setHighlight] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Back/forward navigation changes the search params: follow them.
  useEffect(() => {
    const next = parseQuery(searchParams);
    setQ((cur) =>
      cur.days === next.days && cur.source === next.source && cur.ticker === next.ticker && cur.maxNodes === next.maxNodes ? cur : next,
    );
    setTickerInput(next.ticker);
  }, [searchParams]);

  const update = (patch: Partial<Query>) => {
    const next = { ...q, ...patch };
    setQ(next);
    router.replace(`/graph${toSearch(next)}`, { scroll: false });
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPlaying(false);
    api
      .graph({ days: q.days, source: q.source, max_nodes: q.maxNodes, ticker: q.ticker || undefined })
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setScrub(SCRUB_STEPS);
        setHighlight(null);
        setSelectedId(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg.startsWith("404") ? "The event graph is not available on this API yet (404). Update and restart the backend." : `Could not load the graph. ${msg}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [q, reload]);

  const colorIndex = useMemo(() => buildColorIndex(data?.clusters ?? []), [data]);
  const clusterOrder = useMemo(() => (data?.clusters ?? []).map((c) => c.id).filter((id) => id !== OTHER_CLUSTER), [data]);
  const clusterNames = useMemo(() => new Map((data?.clusters ?? []).map((c) => [c.id, c.name])), [data]);
  const clusterName = useCallback(
    (id: number) => (id === OTHER_CLUSTER ? "Other (no cluster)" : (clusterNames.get(id) ?? `Cluster ${id}`)),
    [clusterNames],
  );
  const nodes = useMemo(() => data?.nodes ?? [], [data]);
  const edges = useMemo(() => data?.edges ?? [], [data]);

  // Time window for the scrubber: the requested window ending at generation time, widened to cover every node.
  const [t0, t1] = useMemo(() => {
    if (!data) return [0, 1];
    const times = data.nodes.map((n) => Date.parse(n.published_at)).filter(Number.isFinite);
    const gen = Date.parse(data.generated_at);
    const end = Math.max(Number.isFinite(gen) ? gen : 0, ...times);
    const start = Math.min(end - data.params.days * 86_400_000, ...times);
    return [start, end > start ? end : start + 1];
  }, [data]);
  const visibleUntil = scrub >= SCRUB_STEPS ? Infinity : t0 + (scrub / SCRUB_STEPS) * (t1 - t0);

  // Play: grow the graph through the window. Reduced motion: discrete steps instead of a smooth sweep.
  useEffect(() => {
    if (!playing) return;
    let pos = scrubRef.current;
    const advance = (by: number): boolean => {
      pos = Math.min(SCRUB_STEPS, pos + by);
      setScrub(pos);
      if (pos >= SCRUB_STEPS) setPlaying(false);
      return pos >= SCRUB_STEPS;
    };
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      const id = window.setInterval(() => {
        if (!document.hidden) advance(SCRUB_STEPS / 10);
      }, 800);
      return () => window.clearInterval(id);
    }
    let raf = 0;
    let last = performance.now();
    const frame = (now: number) => {
      const dt = Math.min(now - last, 100); // a hidden tab pauses rAF; don't jump on return
      last = now;
      if (!advance((dt / PLAY_MS) * SCRUB_STEPS)) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const togglePlay = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (scrub >= SCRUB_STEPS) setScrub(0);
    setPlaying(true);
  };

  const applyTicker = (e?: FormEvent) => {
    e?.preventDefault();
    const t = normaliseTicker(tickerInput);
    if (t && !TICKER_RE.test(t)) {
      setTickerError("Use a ticker symbol like ABCD or BRK.B");
      return;
    }
    setTickerError(null);
    setTickerInput(t);
    if (t !== q.ticker) update({ ticker: t });
  };

  const selected = useMemo(() => nodes.find((n) => n.id === selectedId) ?? null, [nodes, selectedId]);
  const degree = useMemo(
    () => (selectedId === null ? 0 : edges.filter((e) => edgeTypes[e.type] && (e.source === selectedId || e.target === selectedId)).length),
    [edges, edgeTypes, selectedId],
  );
  const otherCount = useMemo(() => nodes.filter((n) => n.cluster === OTHER_CLUSTER).length, [nodes]);
  const shownCount = useMemo(() => nodes.filter((n) => Date.parse(n.published_at) <= visibleUntil).length, [nodes, visibleUntil]);

  return (
    <div className={styles.root}>
      <form className={styles.controls} onSubmit={applyTicker}>
        <div className={styles.control}>
          <span id="graph-days">Window</span>
          <div className="seg" role="group" aria-labelledby="graph-days">
            {DAY_OPTIONS.map((d) => (
              <button key={d} type="button" className={q.days === d ? "on" : ""} aria-pressed={q.days === d} onClick={() => update({ days: d })}>
                {d}d
              </button>
            ))}
          </div>
        </div>
        <label className={styles.control}>
          Source
          <select value={q.source} onChange={(e) => update({ source: e.target.value as GraphSource })}>
            {SOURCES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <div className={styles.control}>
          <label htmlFor="graph-ticker">Ticker</label>
          <div className={styles.tickerForm}>
            <input
              id="graph-ticker"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              placeholder="All"
              maxLength={11}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={tickerError ? true : undefined}
              aria-describedby={tickerError ? "graph-ticker-err" : undefined}
            />
            <button type="submit" className="btn">
              Apply
            </button>
            {q.ticker && (
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setTickerInput("");
                  setTickerError(null);
                  update({ ticker: "" });
                }}
              >
                Clear
              </button>
            )}
          </div>
        </div>
        <label className={styles.control}>
          Max items
          <select value={q.maxNodes} onChange={(e) => update({ maxNodes: Number(e.target.value) })}>
            {[...new Set([...MAX_OPTIONS, q.maxNodes])]
              .sort((a, b) => a - b)
              .map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
          </select>
        </label>
      </form>
      {tickerError && (
        <p id="graph-ticker-err" className="error small" role="alert">
          {tickerError}
        </p>
      )}

      {loading && !data && <GraphSkeleton />}

      {error && (
        <div className={`panel ${styles.center}`} role="alert">
          <p className="error">{error}</p>
          <button type="button" className="btn" onClick={() => setReload((r) => r + 1)}>
            Retry
          </button>
        </div>
      )}

      {data && !error && data.nodes.length === 0 && !loading && (
        <div className={`panel ${styles.center}`}>
          <p>No filings or news in this window{q.ticker ? ` for $${q.ticker}` : ""}.</p>
          <p className="muted small">Try a longer window{q.ticker ? " or clear the ticker filter" : ""}.</p>
        </div>
      )}

      {data && !error && data.nodes.length > 0 && (
        <>
          <div className={styles.edgeToggles} aria-label="Legend and link types">
            <span className={styles.shapeKey}>
              <span className={styles.dotCircle} aria-hidden="true" /> filing
            </span>
            <span className={styles.shapeKey}>
              <span className={styles.dotSquare} aria-hidden="true" /> news
            </span>
            {EDGE_TYPES.map((t) => (
              <label key={t}>
                <input type="checkbox" checked={edgeTypes[t]} onChange={(e) => setEdgeTypes((cur) => ({ ...cur, [t]: e.target.checked }))} />
                <span className={styles.edgeSample} style={{ borderTopStyle: EDGE_BORDER[t] as "solid" }} aria-hidden="true" />
                {EDGE_LABELS[t]}
              </label>
            ))}
            {loading && <span className="muted">Updating…</span>}
          </div>

          <GraphCanvas
            nodes={nodes}
            edges={edges}
            colorIndex={colorIndex}
            clusterOrder={clusterOrder}
            visibleUntil={visibleUntil}
            edgeTypes={edgeTypes}
            highlightCluster={highlight}
            selectedId={selectedId}
            onSelect={setSelectedId}
            clusterName={clusterName}
          />

          <p className={styles.note}>
            {shownCount < nodes.length ? `${shownCount} of ${nodes.length} items shown up to the slider time. ` : `${nodes.length} items, ${edges.length} links. `}
            {data.params.truncated && `Showing ${nodes.length} of ${data.params.total_in_window} items in window. `}
            Links show association (similar text, same company or size, close in time), not cause and effect.
          </p>

          <TimeScrubber
            timeline={data.timeline}
            colorIndex={colorIndex}
            clusterOrder={clusterOrder}
            t0={t0}
            t1={t1}
            value={scrub}
            onChange={(v) => {
              setPlaying(false);
              setScrub(v);
            }}
            playing={playing}
            onTogglePlay={togglePlay}
          />

          <div className={styles.panels}>
            <NodeDetail
              node={selected}
              clusterName={selected ? clusterName(selected.cluster) : ""}
              colorIndex={colorIndex}
              degree={degree}
              onClose={() => setSelectedId(null)}
            />
            <ClusterLegend
              clusters={data.clusters}
              colorIndex={colorIndex}
              otherCount={otherCount}
              highlight={highlight}
              onToggle={(id) => {
                setSelectedId(null);
                setHighlight((h) => (h === id ? null : id));
              }}
            />
          </div>
        </>
      )}

      <HowItWorks method={data?.method} />
    </div>
  );
}
