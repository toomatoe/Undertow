"use client";

import { useEffect, useRef, useState } from "react";

const PAD = { top: 10, right: 12, bottom: 22, left: 64 };

/** About `count` round tick values covering [min, max]. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!(max > min)) return [min];
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/**
 * One time series as a 2px line ("line") or an area hanging below zero ("area").
 * `hover` is the index of the highlighted point; it is lifted so two charts of the
 * same period share one crosshair.
 */
export default function TimeChart({
  points,
  domain,
  height,
  kind,
  format,
  tipFormat,
  label,
  baseline,
  hover,
  onHover,
}: {
  points: [string, number][];
  domain: [number, number];
  height: number;
  kind: "line" | "area";
  format: (v: number) => string;
  tipFormat?: (v: number) => string;
  label: string;
  baseline?: number;
  hover: number | null;
  onHover: (i: number | null) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const n = points.length;
  const innerW = Math.max(10, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;
  const [lo, hi] = domain;
  const x = (i: number) => PAD.left + (n > 1 ? (i / (n - 1)) * innerW : innerW / 2);
  const y = (v: number) => PAD.top + (hi === lo ? innerH / 2 : ((hi - v) / (hi - lo)) * innerH);

  const ticks = niceTicks(lo, hi, kind === "area" ? 2 : 4);
  const line = points.map(([, v], i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const zeroY = y(Math.min(hi, Math.max(lo, 0)));
  const area = n ? `${line}L${x(n - 1).toFixed(1)},${zeroY.toFixed(1)}L${x(0).toFixed(1)},${zeroY.toFixed(1)}Z` : "";

  // One x label per calendar year, at the first point of that year
  const years: { i: number; year: string }[] = [];
  points.forEach(([d], i) => {
    const yr = d.slice(0, 4);
    if (!years.length || years[years.length - 1].year !== yr) years.push({ i, year: yr });
  });

  const move = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!n) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round(((px - PAD.left) / innerW) * (n - 1));
    onHover(Math.max(0, Math.min(n - 1, i)));
  };

  const hp = hover !== null && hover < n ? points[hover] : null;
  const hx = hover !== null ? x(hover) : 0;

  return (
    <div className="bt-chart" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={label}
          onPointerMove={move}
          onPointerLeave={() => onHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line className="bt-grid" x1={PAD.left} x2={PAD.left + innerW} y1={y(t)} y2={y(t)} />
              <text className="bt-axis" x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end">
                {format(t)}
              </text>
            </g>
          ))}
          {years.map(({ i, year }) =>
            i === 0 && n > 1 && x(years[1]?.i ?? n) - x(0) < 30 ? null : (
              <text key={year} className="bt-axis" x={x(i)} y={height - 6} textAnchor="middle">
                {year}
              </text>
            ),
          )}
          {baseline !== undefined && baseline >= lo && baseline <= hi && (
            <line className="bt-base" x1={PAD.left} x2={PAD.left + innerW} y1={y(baseline)} y2={y(baseline)} />
          )}
          {kind === "area" ? (
            <>
              <path className="bt-area" d={area} />
              <path className="bt-area-line" d={line} />
            </>
          ) : (
            <path className="bt-line" d={line} />
          )}
          {hp && (
            <g>
              <line className="bt-cross" x1={hx} x2={hx} y1={PAD.top} y2={PAD.top + innerH} />
              <circle className={kind === "area" ? "bt-dot neg" : "bt-dot"} cx={hx} cy={y(hp[1])} r={4} />
            </g>
          )}
        </svg>
      )}
      {hp && (
        <div
          className="bt-tip"
          role="status"
          style={hx > width / 2 ? { right: width - hx + 10 } : { left: hx + 10 }}
        >
          <span className="muted">Week of {hp[0]}</span>
          <strong>{(tipFormat ?? format)(hp[1])}</strong>
        </div>
      )}
    </div>
  );
}
