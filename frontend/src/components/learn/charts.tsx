// Inline SVG charts for Learn (no chart library, no hooks). Fixed viewBox scaled to the container
// width, so they render identically on the server and in the browser. Sign is shown by a ▲/▼ label
// as well as color.

import type { Bin } from "@/lib/learn/simulations";

import styles from "./learn.module.css";

export interface BarDatum {
  label: string;
  value: number;
  /** Optional class override: "muted" or "flag". */
  tone?: "muted" | "flag";
}

/** Horizontal diverging bars around zero, one row per datum. */
export function HBarChart({
  data,
  format,
  title,
  desc,
  labelWidth = 230,
}: {
  data: BarDatum[];
  format: (v: number) => string;
  title: string;
  desc: string;
  labelWidth?: number;
}) {
  const W = 720;
  const rowH = 26;
  const valueW = 80;
  const H = data.length * rowH + 8;
  const plotW = W - labelWidth - valueW;
  const maxAbs = Math.max(1e-9, ...data.map((d) => Math.abs(d.value)));
  const hasNeg = data.some((d) => d.value < 0);
  const hasPos = data.some((d) => d.value > 0);
  const zeroX = labelWidth + (hasNeg && hasPos ? plotW / 2 : hasNeg ? plotW : 0);
  const scale = hasNeg && hasPos ? plotW / 2 / maxAbs : plotW / maxAbs;
  return (
    <svg className={styles.svg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${desc}`}>
      <title>{title}</title>
      <desc>{desc}</desc>
      <line className={styles.axis} x1={zeroX} x2={zeroX} y1={0} y2={H} />
      {data.map((d, i) => {
        const y = 4 + i * rowH;
        const w = Math.abs(d.value) * scale;
        const x = d.value >= 0 ? zeroX : zeroX - w;
        const cls = d.tone === "muted" ? styles.barMuted : d.tone === "flag" ? styles.barFlag : d.value >= 0 ? styles.barPos : styles.barNeg;
        return (
          <g key={`${d.label}-${i}`}>
            <text x={labelWidth - 8} y={y + rowH / 2 + 4} textAnchor="end">
              {d.label.length > 34 ? `${d.label.slice(0, 33)}…` : d.label}
            </text>
            <rect className={cls} x={x} y={y + 4} width={Math.max(w, 1)} height={rowH - 10} rx={2} />
            <text x={W - 4} y={y + rowH / 2 + 4} textAnchor="end">
              {d.value > 0 ? "▲" : d.value < 0 ? "▼" : "•"} {format(d.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Vertical histogram with optional dashed cut-off lines (e.g. ±1.96 and the Bonferroni |t|). */
export function Histogram({
  bins,
  title,
  desc,
  cuts = [],
  highlight,
  overlay,
  xFormat = (v) => v.toFixed(1),
}: {
  bins: Bin[];
  title: string;
  desc: string;
  cuts?: { x: number; strong?: boolean; label: string }[];
  /** Same bin edges as `bins`; drawn on top in the "negative" color (e.g. the part that vanished). */
  overlay?: Bin[];
  /** Returns the tone of a bin (e.g. beyond a cut-off). */
  highlight?: (b: Bin) => "flag" | "neg" | null;
  xFormat?: (v: number) => string;
}) {
  const W = 720;
  const H = 220;
  const padL = 36;
  const padB = 24;
  const padT = 18;
  const lo = bins[0]?.lo ?? 0;
  const hi = bins[bins.length - 1]?.hi ?? 1;
  const maxC = Math.max(1, ...bins.map((b) => b.count));
  const x = (v: number) => padL + ((v - lo) / (hi - lo)) * (W - padL - 8);
  const y = (c: number) => H - padB - (c / maxC) * (H - padB - padT);
  const ticks = [lo, lo + (hi - lo) / 4, (lo + hi) / 2, lo + (3 * (hi - lo)) / 4, hi];
  return (
    <svg className={styles.svg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${desc}`}>
      <title>{title}</title>
      <desc>{desc}</desc>
      <line className={styles.axis} x1={padL} x2={W - 8} y1={H - padB} y2={H - padB} />
      {bins.map((b, i) => {
        const tone = highlight?.(b) ?? null;
        const cls = tone === "flag" ? styles.barFlag : tone === "neg" ? styles.barNeg : styles.barMuted;
        return <rect key={i} className={cls} x={x(b.lo) + 0.5} y={y(b.count)} width={Math.max(x(b.hi) - x(b.lo) - 1, 0.5)} height={H - padB - y(b.count)} />;
      })}
      {overlay?.map((b, i) =>
        b.count > 0 ? (
          <rect key={`o${i}`} className={styles.barNeg} x={x(b.lo) + 0.5} y={y(b.count)} width={Math.max(x(b.hi) - x(b.lo) - 1, 0.5)} height={H - padB - y(b.count)} />
        ) : null,
      )}
      {ticks.map((t) => (
        <text key={t} x={x(t)} y={H - 6} textAnchor="middle">
          {xFormat(t)}
        </text>
      ))}
      <text x={4} y={padT} textAnchor="start">
        {maxC}
      </text>
      {cuts
        .filter((c) => c.x >= lo && c.x <= hi)
        .map((c) => (
          <g key={`${c.label}-${c.x}`}>
            <line className={c.strong ? styles.cutStrong : styles.cut} x1={x(c.x)} x2={x(c.x)} y1={padT - 6} y2={H - padB} />
            <text x={x(c.x) + 3} y={padT} textAnchor="start">
              {c.label}
            </text>
          </g>
        ))}
    </svg>
  );
}

/** Simple line chart (x numeric) with a dashed horizontal reference line. */
export function LineChart({
  points,
  title,
  desc,
  yMin = 0,
  yMax = 1,
  refY,
  refLabel,
  xLabel,
  yFormat = (v) => v.toFixed(2),
}: {
  points: [number, number][];
  title: string;
  desc: string;
  yMin?: number;
  yMax?: number;
  refY?: number;
  refLabel?: string;
  xLabel: string;
  yFormat?: (v: number) => string;
}) {
  const W = 720;
  const H = 200;
  const padL = 44;
  const padB = 28;
  const padT = 12;
  const xs = points.map((p) => p[0]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const x = (v: number) => padL + ((v - x0) / Math.max(1e-9, x1 - x0)) * (W - padL - 10);
  const y = (v: number) => H - padB - ((Math.min(Math.max(v, yMin), yMax) - yMin) / (yMax - yMin)) * (H - padB - padT);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  return (
    <svg className={styles.svg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${desc}`}>
      <title>{title}</title>
      <desc>{desc}</desc>
      <line className={styles.axis} x1={padL} x2={W - 10} y1={H - padB} y2={H - padB} />
      <line className={styles.axis} x1={padL} x2={padL} y1={padT} y2={H - padB} />
      {[yMin, (yMin + yMax) / 2, yMax].map((t) => (
        <text key={t} x={padL - 6} y={y(t) + 4} textAnchor="end">
          {yFormat(t)}
        </text>
      ))}
      <text x={padL} y={H - 8} textAnchor="start">
        {x0}
      </text>
      <text x={W - 10} y={H - 8} textAnchor="end">
        {x1}
      </text>
      <text x={(W + padL) / 2} y={H - 8} textAnchor="middle">
        {xLabel}
      </text>
      {refY !== undefined && (
        <g>
          <line className={styles.cut} x1={padL} x2={W - 10} y1={y(refY)} y2={y(refY)} />
          {refLabel && (
            <text x={W - 12} y={y(refY) - 4} textAnchor="end">
              {refLabel}
            </text>
          )}
        </g>
      )}
      <path className={styles.line} d={d} />
    </svg>
  );
}
