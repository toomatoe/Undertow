"use client";

import { useEffect, useRef, useState } from "react";

import { pct } from "@/lib/format";

import { niceTicks } from "../backtest/TimeChart";

const PAD = { top: 10, right: 12, bottom: 22, left: 56 };

export interface RunningPoint {
  label: string; // ticker + date, for the tooltip
  value: number; // running average after this result
  n: number;
}

/** Running average of completed results, one point per result, with an optional reference line. */
export default function RunningMeanChart({ points, reference, height = 200 }: { points: RunningPoint[]; reference: number | null; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = points.length;
  const vals = [0, ...points.map((p) => p.value), ...(reference !== null ? [reference] : [])];
  const ticks0 = niceTicks(Math.min(...vals), Math.max(...vals), 4);
  const step = ticks0.length > 1 ? ticks0[1] - ticks0[0] : 0.01;
  const lo = Math.floor(Math.min(...vals) / step) * step;
  const hi = Math.ceil(Math.max(...vals) / step) * step || step;
  const ticks = niceTicks(lo, hi, 4);
  const innerW = Math.max(10, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (n > 1 ? (i / (n - 1)) * innerW : innerW / 2);
  const y = (v: number) => PAD.top + (hi === lo ? innerH / 2 : ((hi - v) / (hi - lo)) * innerH);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const fmt = (v: number) => (v === 0 ? "0%" : pct(v, Math.abs(step) < 0.01 ? 1 : 0));

  const move = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!n) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - rect.left - PAD.left) / innerW) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  const hp = hover !== null && hover < n ? points[hover] : null;
  const hx = hover !== null ? x(hover) : 0;
  const last = points[n - 1];

  return (
    <div className="bt-chart" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Running average 20-day result after ${n} completed filings: ${last ? pct(last.value) : "none"}${reference !== null ? `; backtest expected ${pct(reference)}` : ""}`}
          onPointerMove={move}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line className="bt-grid" x1={PAD.left} x2={PAD.left + innerW} y1={y(t)} y2={y(t)} />
              <text className="bt-axis" x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end">
                {fmt(t)}
              </text>
            </g>
          ))}
          <line className="bt-base" x1={PAD.left} x2={PAD.left + innerW} y1={y(0)} y2={y(0)} />
          {reference !== null && (
            <g>
              <line className="tr-ref" x1={PAD.left} x2={PAD.left + innerW} y1={y(reference)} y2={y(reference)} />
              <text className="bt-axis" x={PAD.left + innerW} y={y(reference) - 4} textAnchor="end">
                Backtest expected {pct(reference)}
              </text>
            </g>
          )}
          <text className="bt-axis" x={PAD.left} y={height - 6}>
            1st result
          </text>
          <text className="bt-axis" x={PAD.left + innerW} y={height - 6} textAnchor="end">
            {n} results
          </text>
          <path className="bt-line" d={line} />
          {last && <circle className="bt-dot" cx={x(n - 1)} cy={y(last.value)} r={3} />}
          {hp && (
            <g>
              <line className="bt-cross" x1={hx} x2={hx} y1={PAD.top} y2={PAD.top + innerH} />
              <circle className="bt-dot" cx={hx} cy={y(hp.value)} r={4} />
            </g>
          )}
        </svg>
      )}
      {hp && (
        <div className="bt-tip" role="status" style={hx > width / 2 ? { right: width - hx + 10 } : { left: hx + 10 }}>
          <span className="muted">
            After {hp.n} result{hp.n === 1 ? "" : "s"} (latest {hp.label})
          </span>
          <strong>
            {hp.value > 0 ? "▲" : hp.value < 0 ? "▼" : "•"} {pct(hp.value)}
          </strong>
        </div>
      )}
    </div>
  );
}
