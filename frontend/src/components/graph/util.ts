/** Pure helpers for the Event graph (no React, no fetch). */
import type { GraphCluster, GraphEdgeType } from "@/lib/api";

/** Number of categorical colours defined as --g-c0..--g-c9 in graph.module.css. */
export const PALETTE_SIZE = 10;

export const OTHER_CLUSTER = -1;

export const EDGE_TYPES: GraphEdgeType[] = ["contextual", "spatial", "temporal"];

export const EDGE_LABELS: Record<GraphEdgeType, string> = {
  contextual: "Similar text",
  spatial: "Same company or size",
  temporal: "Close in time",
};

/** Canvas dash pattern per edge type (screen pixels): contextual solid, spatial dotted, temporal dashed. */
export const EDGE_DASH: Record<GraphEdgeType, number[]> = {
  contextual: [],
  spatial: [1.5, 3],
  temporal: [6, 4],
};

/** CSS border style matching EDGE_DASH, for the legend samples. */
export const EDGE_BORDER: Record<GraphEdgeType, string> = {
  contextual: "solid",
  spatial: "dotted",
  temporal: "dashed",
};

/** Cluster id -> palette slot, in the order the server lists clusters (largest first). "Other" has no slot. */
export function buildColorIndex(clusters: GraphCluster[]): Map<number, number> {
  const m = new Map<number, number>();
  let i = 0;
  for (const c of clusters) {
    if (c.id === OTHER_CLUSTER || m.has(c.id)) continue;
    m.set(c.id, i % PALETTE_SIZE);
    i++;
  }
  return m;
}

/** CSS colour for a cluster id (a var() reference, usable in inline styles and SVG fills). */
export function clusterColorVar(colorIndex: Map<number, number>, cluster: number): string {
  const i = colorIndex.get(cluster);
  return i === undefined ? "var(--g-other)" : `var(--g-c${i})`;
}

/** Mean sentiment as a word, same +-0.15 thresholds as sentimentClass() / the backend label rule. */
export function moodWord(score: number | null | undefined): string {
  if (score === null || score === undefined || !Number.isFinite(score)) return "n/a";
  if (score > 0.15) return "positive";
  if (score < -0.15) return "negative";
  return "neutral";
}

/** Ticker filter: uppercase letters/digits with optional . or - (e.g. BRK.B), 1-10 chars. */
export const TICKER_RE = /^[A-Z][A-Z0-9.-]{0,9}$/;

export function normaliseTicker(raw: string | null | undefined): string {
  return (raw ?? "").trim().toUpperCase().replace(/^\$/, "");
}

/** Only http(s) links are rendered as clickable source links. */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return /^https?:\/\//i.test(url) ? url : null;
}

export function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
