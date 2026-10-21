"use client";

import Link from "next/link";

import type { GraphNode } from "@/lib/api";
import { formatScore, sentimentClass, SIZE_LABELS, timeAgo } from "@/lib/format";

import styles from "./graph.module.css";
import { clusterColorVar, safeHttpUrl, TICKER_RE } from "./util";

interface Props {
  node: GraphNode | null;
  clusterName: string;
  colorIndex: Map<number, number>;
  /** Number of links to this node among the edges currently shown. */
  degree: number;
  onClose: () => void;
}

export default function NodeDetail({ node, clusterName, colorIndex, degree, onClose }: Props) {
  if (!node) {
    return (
      <section className="panel" aria-labelledby="graph-detail-h">
        <h2 id="graph-detail-h">Details</h2>
        <p className="muted small">Click or tap a node to see the filing or article behind it.</p>
      </section>
    );
  }
  const tickers = [...new Set([node.ticker, ...node.tickers].filter((t): t is string => !!t))];
  const url = safeHttpUrl(node.url);
  const when = new Date(node.published_at);
  return (
    <section className={`panel ${styles.detail}`} aria-labelledby="graph-detail-h">
      <div className="panel-head">
        <h2 id="graph-detail-h">Details</h2>
        <button type="button" className="btn" onClick={onClose}>
          Clear
        </button>
      </div>
      <p className={styles.detailTitle}>{node.title}</p>
      <dl>
        <dt>Kind</dt>
        <dd>{node.kind === "filing" ? `SEC filing${node.form ? ` · ${node.form}` : ""}` : "News article"}</dd>
        <dt>Source</dt>
        <dd>{node.source_name}</dd>
        <dt>Published</dt>
        <dd>
          <time dateTime={node.published_at}>{Number.isNaN(when.getTime()) ? node.published_at : when.toLocaleString()}</time>{" "}
          <span className="muted">({timeAgo(node.published_at)})</span>
        </dd>
        {tickers.length > 0 && (
          <>
            <dt>Tickers</dt>
            <dd className={styles.chips}>
              {tickers.map((t) =>
                TICKER_RE.test(t) ? (
                  <Link key={t} href={`/ticker/${encodeURIComponent(t)}`} className="chip">
                    ${t}
                  </Link>
                ) : (
                  <span key={t} className="chip">
                    ${t}
                  </span>
                ),
              )}
              {node.size_bucket && <span className="muted small">{SIZE_LABELS[node.size_bucket] ?? node.size_bucket}</span>}
            </dd>
          </>
        )}
        <dt>Signals</dt>
        <dd>{node.signal_labels.length > 0 ? node.signal_labels.join(", ") : <span className="muted">none</span>}</dd>
        <dt>Sentiment</dt>
        <dd>
          <span className={`sent ${sentimentClass(node.sentiment)}`}>{formatScore(node.sentiment)}</span>
          {node.sentiment === null && <span className="muted"> not scored</span>}
        </dd>
        <dt>Cluster</dt>
        <dd>
          <span
            aria-hidden="true"
            style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, marginRight: 6, background: clusterColorVar(colorIndex, node.cluster) }}
          />
          {clusterName}
        </dd>
        <dt>Links</dt>
        <dd>
          {degree} shown <span className="muted">(associations, not causes)</span>
        </dd>
      </dl>
      {url && (
        <a href={url} target="_blank" rel="noopener noreferrer" className="key">
          {node.kind === "filing" ? "Open the filing on EDGAR ↗" : "Open the article ↗"}
        </a>
      )}
    </section>
  );
}
