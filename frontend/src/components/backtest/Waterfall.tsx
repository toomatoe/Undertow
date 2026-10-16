"use client";

import { useState } from "react";

import type { BacktestPeriod } from "@/lib/api";
import { fmtNum, pct } from "@/lib/format";

import { PERIOD_TITLES } from "./parts";

type Step = BacktestPeriod["waterfall"][number];

/** Each row floats from the previous step's value to its own; the first and last rows are totals from zero. */
function rowsFor(steps: Step[]) {
  return steps.map((s, i) => {
    const total = i === 0 || i === steps.length - 1;
    const from = total ? 0 : steps[i - 1].avg_trade_return;
    const to = s.avg_trade_return;
    return { s, from, to, delta: to - from, total };
  });
}

function Marker({ v }: { v: number }) {
  const cls = Math.abs(v) < 0.00005 ? "dv-zero" : v > 0 ? "dv-pos" : "dv-neg";
  const mark = Math.abs(v) < 0.00005 ? "•" : v > 0 ? "▲" : "▼";
  return (
    <span className={`dv ${cls}`}>
      <span aria-hidden="true">{mark}</span> {pct(v, Math.abs(v) < 0.001 ? 2 : 1)}
    </span>
  );
}

function PeriodWaterfall({ pkey, p, domain }: { pkey: string; p: BacktestPeriod; domain: [number, number] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [lo, hi] = domain;
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const rows = rowsFor(p.waterfall);
  return (
    <figure className="bt-facet">
      <figcaption>
        <strong>
          {pkey}: {PERIOD_TITLES[pkey]?.title ?? p.period.label}
        </strong>
        <span className="muted small">Average return per trade after each step</span>
      </figcaption>
      <div className="bt-wf" onMouseLeave={() => setHover(null)}>
        {rows.map((r, i) => {
          const a = Math.min(r.from, r.to);
          const b = Math.max(r.from, r.to);
          const sign = r.total ? r.to : r.delta;
          const flat = Math.abs(sign) < 0.00005;
          return (
            <div
              key={r.s.step}
              className={`bt-wf-row ${hover === i ? "hover" : ""} ${r.total ? "total" : ""}`}
              tabIndex={0}
              onMouseEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            >
              <span className="bt-wf-label">
                {r.s.step}
              </span>
              <span className="bt-wf-track">
                <span className="bt-wf-zero" style={{ left: `${x(0)}%` }} />
                {!r.total && <span className="bt-wf-from" style={{ left: `${x(r.from)}%` }} />}
                <span
                  className={`bt-wf-bar ${flat ? "flat" : sign > 0 ? "pos" : "neg"}`}
                  style={{ left: `${x(a)}%`, width: `max(2px, ${x(b) - x(a)}%)` }}
                />
              </span>
              <span className="bt-wf-value">
                {r.total ? (
                  <Marker v={r.to} />
                ) : (
                  <>
                    <Marker v={r.delta} /> <span className="muted">→ {pct(r.to)}</span>
                  </>
                )}
              </span>
              {hover === i && (
                <div className="bt-wf-tip" role="status">
                  <strong>{r.s.step}</strong>
                  <span>Average trade {pct(r.s.avg_trade_return, 2)} · median {pct(r.s.median_trade_return, 2)}</span>
                  <span>
                    {r.s.trades.toLocaleString()} trades · portfolio total return {pct(r.s.total_return)} · Sharpe {fmtNum(r.s.sharpe)}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </figure>
  );
}

export default function Waterfall({ periods }: { periods: [string, BacktestPeriod][] }) {
  const withSteps = periods.filter(([, p]) => p.waterfall?.length);
  if (!withSteps.length) return null;
  const vals = withSteps.flatMap(([, p]) => p.waterfall.map((s) => s.avg_trade_return));
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const pad = (hi - lo) * 0.05 || 0.01;
  const domain: [number, number] = [lo - pad, hi + pad];
  return (
    <div className="bt-two">
      {withSteps.map(([k, p]) => (
        <PeriodWaterfall key={k} pkey={k} p={p} domain={domain} />
      ))}
    </div>
  );
}
