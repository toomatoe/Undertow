"use client";

import type { Evidence, GraphCluster } from "@/lib/api";
import { formatScore, pct } from "@/lib/format";

import styles from "./graph.module.css";
import { clusterColorVar, moodWord, OTHER_CLUSTER } from "./util";

interface Props {
  clusters: GraphCluster[];
  colorIndex: Map<number, number>;
  /** Count of nodes outside any named cluster (shown as "Other"). */
  otherCount: number;
  highlight: number | null;
  onToggle: (id: number) => void;
}

/** Same wording as the evidence line on ArticleCard, explicitly labelled historical and hypothetical. */
function EvidenceText({ ev, signalLabel, note }: { ev: Evidence; signalLabel: string; note: string }) {
  const verdict = ev.significant ? "edge after costs" : ev.mean_net > 0 ? "not significant" : "no edge after costs";
  return (
    <span className={styles.evidence} title={`t = ${ev.t_stat}, n = ${ev.n} past events`}>
      <b>Historical event study (hypothetical):</b> {signalLabel}, past {ev.bucket} caps: {pct(ev.mean_abnormal)} vs index over{" "}
      {ev.horizon_days}d
      {ev.excess_vs_baseline !== null && ev.excess_vs_baseline !== undefined && ` (${pct(ev.excess_vs_baseline)} vs ordinary days)`}, n=
      {ev.n} · {verdict}
      {note ? `. ${note}` : ""}
    </span>
  );
}

export default function ClusterLegend({ clusters, colorIndex, otherCount, highlight, onToggle }: Props) {
  const named = clusters.filter((c) => c.id !== OTHER_CLUSTER);
  const otherCluster = clusters.find((c) => c.id === OTHER_CLUSTER);
  return (
    <section className="panel" aria-labelledby="graph-legend-h">
      <h2 id="graph-legend-h">Clusters</h2>
      <p className="muted small">Click a cluster to highlight it in the graph. Names come from each cluster&apos;s most distinctive terms.</p>
      {named.length === 0 && <p className="muted small">No clusters formed in this window.</p>}
      <ul className={styles.legend}>
        {named.map((c) => {
          const mood = moodWord(c.mean_sentiment);
          const sigLabel = c.evidence ? (c.signal_mix.find((s) => s.code === c.evidence?.signal)?.label ?? c.evidence.signal) : "";
          return (
            <li key={c.id}>
              <button type="button" className={styles.legendItem} aria-pressed={highlight === c.id} onClick={() => onToggle(c.id)}>
                <span className={styles.swatch} style={{ background: clusterColorVar(colorIndex, c.id) }} aria-hidden="true" />
                <span className={styles.legendBody}>
                  <span className={styles.legendName}>
                    {c.name}
                    {c.name_source === "llm" && (
                      <span className={styles.aiBadge} title="Name suggested by Claude from the cluster's distinctive terms">
                        AI-named
                      </span>
                    )}
                  </span>
                  <span className="muted">
                    {c.size} item{c.size === 1 ? "" : "s"}
                    {c.tickers.length > 0 && <> · {c.tickers.slice(0, 5).map((t) => `$${t}`).join(" ")}</>}
                  </span>
                  {c.signal_mix.length > 0 && (
                    <span>
                      Signals:{" "}
                      {c.signal_mix
                        .slice(0, 4)
                        .map((s) => `${s.label} ×${s.count}`)
                        .join(", ")}
                    </span>
                  )}
                  <span>
                    Mood: {mood}
                    {mood !== "n/a" && ` (${formatScore(c.mean_sentiment)}, n=${c.sentiment_n})`}
                  </span>
                  {/* The note is the disclaimer for an evidence line; without evidence it would stand alone. */}
                  {c.evidence && <EvidenceText ev={c.evidence} signalLabel={sigLabel} note={c.evidence_note} />}
                </span>
              </button>
            </li>
          );
        })}
        {(otherCount > 0 || otherCluster) && (
          <li>
            <button
              type="button"
              className={styles.legendItem}
              aria-pressed={highlight === OTHER_CLUSTER}
              onClick={() => onToggle(OTHER_CLUSTER)}
            >
              <span className={styles.swatch} style={{ background: "var(--g-other)" }} aria-hidden="true" />
              <span className={styles.legendBody}>
                <span className={styles.legendName}>Other</span>
                <span className="muted">
                  {otherCluster?.size ?? otherCount} item{(otherCluster?.size ?? otherCount) === 1 ? "" : "s"} not in any cluster
                </span>
              </span>
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}
