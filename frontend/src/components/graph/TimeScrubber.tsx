"use client";

import { useMemo } from "react";

import type { GraphTimeline } from "@/lib/api";

import styles from "./graph.module.css";
import { clusterColorVar, formatWhen, OTHER_CLUSTER } from "./util";

export const SCRUB_STEPS = 1000;

interface Props {
  timeline: GraphTimeline;
  colorIndex: Map<number, number>;
  /** Cluster ids in legend order (stacking order, bottom first). */
  clusterOrder: number[];
  t0: number;
  t1: number;
  /** 0..SCRUB_STEPS */
  value: number;
  onChange: (v: number) => void;
  playing: boolean;
  onTogglePlay: () => void;
}

const W = 1000;
const H = 100;

/** Stacked area of the timeline buckets (coloured by cluster) above a range input over the window, with play/pause. */
export default function TimeScrubber({ timeline, colorIndex, clusterOrder, t0, t1, value, onChange, playing, onTogglePlay }: Props) {
  const span = Math.max(t1 - t0, 1);
  const at = t0 + (value / SCRUB_STEPS) * span;

  const areas = useMemo(() => {
    const buckets = timeline.buckets
      .map((b) => ({ t: Date.parse(b.t), counts: b.counts }))
      .filter((b) => Number.isFinite(b.t))
      .sort((a, b) => a.t - b.t);
    if (buckets.length === 0) return [];
    const keys = [...clusterOrder.map(String)];
    for (const b of buckets) for (const k of Object.keys(b.counts)) if (!keys.includes(k)) keys.push(k);
    // "other" on top so the named clusters sit on the baseline.
    keys.sort((a, b) => (Number(a) === OTHER_CLUSTER ? 1 : 0) - (Number(b) === OTHER_CLUSTER ? 1 : 0));
    const totals = buckets.map((b) => Object.values(b.counts).reduce((s, c) => s + (Number.isFinite(c) ? c : 0), 0));
    const max = Math.max(1, ...totals);
    const xOf = (t: number) => Math.min(Math.max(((t - t0) / span) * W, 0), W);
    const step = buckets.length > 1 ? (buckets[buckets.length - 1].t - buckets[0].t) / (buckets.length - 1) : span / 24;
    const base = buckets.map(() => 0);
    return keys.map((k) => {
      const lower = [...base];
      buckets.forEach((b, i) => {
        base[i] += Number.isFinite(b.counts[k]) ? b.counts[k] : 0;
      });
      // Step shape: each bucket covers [t, t + step).
      const top: string[] = [];
      const bottom: string[] = [];
      buckets.forEach((b, i) => {
        const x0 = xOf(b.t);
        const x1 = xOf(b.t + step);
        const yt = H - (base[i] / max) * (H - 4);
        const yb = H - (lower[i] / max) * (H - 4);
        top.push(`${x0.toFixed(1)},${yt.toFixed(1)} ${x1.toFixed(1)},${yt.toFixed(1)}`);
        bottom.unshift(`${x1.toFixed(1)},${yb.toFixed(1)} ${x0.toFixed(1)},${yb.toFixed(1)}`);
      });
      return { key: k, points: `${top.join(" ")} ${bottom.join(" ")}`, color: clusterColorVar(colorIndex, Number(k)) };
    });
  }, [timeline, clusterOrder, colorIndex, t0, span]);

  const cursorX = (value / SCRUB_STEPS) * W;

  return (
    <div className={styles.timeline}>
      <svg className={styles.spark} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        {areas.map((a) => (
          <polygon key={a.key} points={a.points} style={{ fill: a.color }} opacity={0.85} />
        ))}
        {value < SCRUB_STEPS && <rect x={cursorX} y={0} width={W - cursorX} height={H} style={{ fill: "var(--g-canvas)" }} opacity={0.7} />}
        <line x1={cursorX} x2={cursorX} y1={0} y2={H} style={{ stroke: "var(--text)" }} strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className={styles.scrubRow}>
        <button type="button" className="btn" onClick={onTogglePlay} aria-pressed={playing}>
          {playing ? "Pause" : "Play"}
        </button>
        <input
          type="range"
          min={0}
          max={SCRUB_STEPS}
          step={1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-label="Show items published up to this time"
          aria-valuetext={formatWhen(new Date(at).toISOString())}
        />
        <time dateTime={new Date(at).toISOString()}>{value >= SCRUB_STEPS ? "Now" : formatWhen(new Date(at).toISOString())}</time>
      </div>
      <p className={styles.note}>
        Items per {timeline.granularity}, coloured by cluster. Drag the slider or press Play to replay how the window unfolded:
        items appear at their publication time.
      </p>
    </div>
  );
}
