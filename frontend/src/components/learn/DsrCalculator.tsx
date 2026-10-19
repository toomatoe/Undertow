"use client";

import { useMemo, useState } from "react";

import type { DsrPrefill } from "@/lib/learn/live";
import { dsr, expectedMaxSharpe, psrFromStats } from "@/lib/learn/stats";

import { LineChart } from "./charts";
import { NumberField } from "./controls";
import styles from "./learn.module.css";
import { LiveTag, Stat } from "./parts";

interface Inputs {
  sharpe: number;
  n: number;
  skew: number;
  kurt: number;
  trials: number;
  sdTrials: number;
}

const TEXTBOOK: Inputs = { sharpe: 1.5, n: 756, skew: -0.5, kurt: 6, trials: 20, sdTrials: 0.5 };

const fromPrefill = (p: DsrPrefill): Inputs => ({
  sharpe: p.inputs.sharpeAnnual,
  n: p.inputs.n,
  skew: p.inputs.skew,
  kurt: p.inputs.kurt,
  trials: p.trials,
  sdTrials: Number(p.sdTrials.toFixed(4)),
});

const prob = (v: number) => (v < 0.001 && v > 0 ? "< 0.001" : v.toFixed(3));

/**
 * PSR / DSR calculator mirroring backend/app/backtest/stats.py (psr, expected_max_sharpe, dsr).
 * `prefill`: one entry per backtest period, from lib/learn/live dsrPrefill(); empty when the report is unavailable.
 */
export default function DsrCalculator({ prefill, reportDate }: { prefill: DsrPrefill[]; reportDate: string | null }) {
  const [source, setSource] = useState<string>(prefill[0]?.period ?? "textbook");
  const [x, setX] = useState<Inputs>(prefill[0] ? fromPrefill(prefill[0]) : TEXTBOOK);
  const set = (k: keyof Inputs) => (v: number) => setX((cur) => ({ ...cur, [k]: v }));

  const pick = (key: string) => {
    setSource(key);
    const p = prefill.find((q) => q.period === key);
    setX(p ? fromPrefill(p) : TEXTBOOK);
  };

  const stats = { sharpeAnnual: x.sharpe, n: Math.round(x.n), skew: x.skew, kurt: x.kurt };
  const psr0 = psrFromStats(stats, 0);
  const d = dsr(stats, x.sdTrials, Math.round(x.trials));
  const curve = useMemo(() => {
    const pts: [number, number][] = [];
    for (let t = 1; t <= 100; t++) pts.push([t, psrFromStats({ sharpeAnnual: x.sharpe, n: Math.round(x.n), skew: x.skew, kurt: x.kurt }, expectedMaxSharpe(x.sdTrials, t))]);
    return pts;
  }, [x]);
  const active = prefill.find((p) => p.period === source);
  const unchanged = active && JSON.stringify(fromPrefill(active)) === JSON.stringify(x);

  return (
    <section className={styles.panel} aria-label="PSR and deflated Sharpe ratio calculator">
      <h3>Calculator: probabilistic and deflated Sharpe ratio</h3>
      <div className={styles.controls}>
        <label>
          Pre-fill from
          <select value={source} onChange={(e) => pick(e.target.value)}>
            {prefill.map((p) => (
              <option key={p.period} value={p.period}>
                Backtest period {p.period} ({p.label})
              </option>
            ))}
            <option value="textbook">Textbook example</option>
          </select>
        </label>
        <NumberField label="Sharpe (annual)" value={x.sharpe} onChange={set("sharpe")} min={-10} max={10} step={0.01} />
        <NumberField label="Daily returns (n)" value={x.n} onChange={set("n")} min={10} max={100000} />
        <NumberField label="Skew" value={x.skew} onChange={set("skew")} min={-50} max={50} step={0.01} hint="normal = 0" />
        <NumberField label="Kurtosis" value={x.kurt} onChange={set("kurt")} min={1} max={500} step={0.01} hint="plain fourth moment, normal = 3" />
        <NumberField label="Trials (configs tried)" value={x.trials} onChange={set("trials")} min={1} max={10000} />
        <NumberField label="Sd of trial Sharpes" value={x.sdTrials} onChange={set("sdTrials")} min={0} max={10} step={0.01} />
      </div>
      <div className={styles.stats}>
        <Stat label="PSR vs Sharpe 0" value={prob(psr0)} sub="P(true Sharpe > 0)" />
        <Stat label="Luck benchmark" value={d.benchmark.toFixed(2)} sub={`best of ${Math.round(x.trials)} by chance (annual Sharpe)`} />
        <Stat label="Deflated Sharpe (DSR)" value={prob(d.dsr)} sub={d.dsr >= 0.95 ? "clears the 0.95 gate" : "below the 0.95 gate"} />
      </div>
      <LineChart
        points={curve}
        title="Deflated Sharpe ratio vs number of configurations tried"
        desc="Same returns; every extra trial raises the luck benchmark and lowers the DSR."
        refY={0.95}
        refLabel="0.95 gate"
        xLabel="trials"
      />
      {active && (
        <p className="small">
          <LiveTag kind="hypothetical" date={reportDate} what="backtest report" /> Check against the report for period {active.period}:
          report PSR {active.reportPsr.toFixed(3)} vs recomputed {active.recomputedPsr.toFixed(3)}; report DSR{" "}
          {active.reportDsr === null ? "—" : active.reportDsr.toFixed(3)} vs recomputed {active.recomputedDsr.toFixed(3)}
          {active.reportDsr !== null && (Math.abs(active.reportDsr - active.recomputedDsr) <= 0.01 ? " (within 0.01)." : " (differs by more than 0.01).")}
          {!unchanged && " You have edited the inputs, so the numbers above no longer describe the report."}
        </p>
      )}
      <p className="muted small">
        Inputs used from the report: the annualized Sharpe, skew and kurtosis (rounded to 2 decimals) and the number of trials.{" "}
        {active?.exactN
          ? "The number of daily returns (n) is the exact count the report published."
          : <>The report does not publish the number of daily returns, so <em>n</em> is estimated from the period&apos;s first and last trading dates (weekdays × 252/261 − 1).</>}{" "}
        {active?.exactSdTrials
          ? "The sd of trial Sharpes is the value the report published."
          : "The report does not publish the sd of trial Sharpes, so it is backed out of the report's luck benchmark (luck Sharpe ÷ expected-maximum factor for that many trials)."}{" "}
        Formulas: Bailey &amp; López de Prado (2012, 2014), as implemented in <code>backend/app/backtest/stats.py</code>.
      </p>
    </section>
  );
}
