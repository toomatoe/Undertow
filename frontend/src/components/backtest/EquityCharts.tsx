"use client";

import { useState } from "react";

import type { BacktestPeriod } from "@/lib/api";
import { formatUsd, pct } from "@/lib/format";

import { PERIOD_TITLES } from "./parts";
import TimeChart, { niceTicks } from "./TimeChart";

const shortUsd = (v: number) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v / 1e3)}K`);
/** Widen [min, max] outward to the nearest round tick so the top and bottom gridlines frame the data. */
function snap(min: number, max: number, count: number): [number, number] {
  const t = niceTicks(min, max, count);
  const step = t.length > 1 ? t[1] - t[0] : Math.max(Math.abs(max - min), 1);
  return [Math.floor(min / step) * step, Math.ceil(max / step) * step];
}

const ddFmt =(v: number) => (v === 0 ? "0%" : pct(v, Math.abs(v) < 0.1 ? 1 : 0));

function PeriodCharts({
  pkey,
  p,
  eqDomain,
  ddDomain,
}: {
  pkey: string;
  p: BacktestPeriod;
  eqDomain: [number, number];
  ddDomain: [number, number];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const start = p.metrics.start_equity;
  const end = p.metrics.end_equity;
  return (
    <figure className="bt-facet">
      <figcaption>
        <strong>
          {pkey}: {PERIOD_TITLES[pkey]?.title ?? p.period.label}
        </strong>
        <span className="muted small">
          {p.period.label} · {formatUsd(start)} became {formatUsd(end)}
        </span>
      </figcaption>
      <p className="muted small bt-chart-title">Account value</p>
      <TimeChart
        points={p.equity_curve}
        domain={eqDomain}
        height={200}
        kind="line"
        format={shortUsd}
        tipFormat={(v) => formatUsd(v)}
        label={`Account value for period ${pkey}`}
        baseline={start}
        hover={hover}
        onHover={setHover}
      />
      <p className="muted small bt-chart-title">Drop from previous high</p>
      <TimeChart
        points={p.drawdown_curve}
        domain={ddDomain}
        height={90}
        kind="area"
        format={ddFmt}
        label={`Drawdown for period ${pkey}`}
        hover={hover}
        onHover={setHover}
      />
    </figure>
  );
}

export default function EquityCharts({ periods }: { periods: [string, BacktestPeriod][] }) {
  const eq = periods.flatMap(([, p]) => p.equity_curve.map(([, v]) => v));
  const dd = periods.flatMap(([, p]) => p.drawdown_curve.map(([, v]) => v));
  const eqDomain = snap(Math.min(...eq), Math.max(...eq), 4);
  const ddDomain: [number, number] = [snap(Math.min(-0.01, ...dd), 0, 2)[0], 0];
  return (
    <div className="bt-two">
      {periods.map(([k, p]) => (
        <PeriodCharts key={k} pkey={k} p={p} eqDomain={eqDomain} ddDomain={ddDomain} />
      ))}
    </div>
  );
}
