"use client";

import { useEffect, useRef, useState } from "react";

import type { PaperEquityPoint } from "@/lib/api";
import { formatUsd } from "@/lib/format";

import { niceTicks } from "../backtest/TimeChart";

const PAD = { top: 12, right: 12, bottom: 22, left: 64 };

function day(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** Hypothetical equity over time with a dashed line at the starting capital (same style as the backtest charts). */
export default function EquityChart({ points, start, height = 240 }: { points: PaperEquityPoint[]; start: number; height?: number }) {
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
  const vals = [start, ...points.map((p) => p.equity)];
  const rawLo = Math.min(...vals);
  const rawHi = Math.max(...vals);
  const span = rawHi - rawLo || Math.max(1, start * 0.01);
  const ticks0 = niceTicks(rawLo - span * 0.05, rawHi + span * 0.05, 4);
  const step = ticks0.length > 1 ? ticks0[1] - ticks0[0] : span;
  const lo = Math.floor((rawLo - span * 0.05) / step) * step;
  const hi = Math.ceil((rawHi + span * 0.05) / step) * step;
  const ticks = niceTicks(lo, hi, 4);
  const innerW = Math.max(10, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (n > 1 ? (i / (n - 1)) * innerW : innerW / 2);
  const y = (v: number) => PAD.top + (hi === lo ? innerH / 2 : ((hi - v) / (hi - lo)) * innerH);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join("");

  const move = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!n) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - rect.left - PAD.left) / innerW) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  const hp = hover !== null && hover < n ? points[hover] : null;
  const hx = hover !== null ? x(hover) : 0;
  const last = points[n - 1];
  const lastBelow = last ? last.equity < start : false;

  return (
    <div className="bt-chart" ref={ref}>
      {width > 0 && n > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Hypothetical equity from ${day(points[0].date)} to ${day(last.date)}: ${formatUsd(start)} start, ${formatUsd(last.equity)} latest`}
          onPointerMove={move}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line className="bt-grid" x1={PAD.left} x2={PAD.left + innerW} y1={y(t)} y2={y(t)} />
              <text className="bt-axis" x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end">
                {formatUsd(t)}
              </text>
            </g>
          ))}
          <line className="bt-base" x1={PAD.left} x2={PAD.left + innerW} y1={y(start)} y2={y(start)} />
          <text className="bt-axis" x={PAD.left + 4} y={y(start) - 4}>
            Start {formatUsd(start)}
          </text>
          <text className="bt-axis" x={PAD.left} y={height - 6}>
            {day(points[0].date)}
          </text>
          {n > 1 && (
            <text className="bt-axis" x={PAD.left + innerW} y={height - 6} textAnchor="end">
              {day(last.date)}
            </text>
          )}
          <path className="bt-line" d={line} />
          {last && <circle className={`bt-dot${lastBelow ? " neg" : ""}`} cx={x(n - 1)} cy={y(last.equity)} r={3} />}
          {hp && (
            <g>
              <line className="bt-cross" x1={hx} x2={hx} y1={PAD.top} y2={PAD.top + innerH} />
              <circle className={`bt-dot${hp.equity < start ? " neg" : ""}`} cx={hx} cy={y(hp.equity)} r={4} />
            </g>
          )}
        </svg>
      )}
      {hp && (
        <div className="bt-tip" role="status" style={hx > width / 2 ? { right: width - hx + 10 } : { left: hx + 10 }}>
          <span className="muted">{day(hp.date)} (hypothetical)</span>
          <strong>
            {hp.equity > start ? "▲" : hp.equity < start ? "▼" : "•"} {formatUsd(hp.equity)}
          </strong>
          <span className="muted">
            {hp.open_positions} open position{hp.open_positions === 1 ? "" : "s"}
          </span>
        </div>
      )}
    </div>
  );
}
