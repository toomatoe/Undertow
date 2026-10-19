// Pure helpers that pull the numbers a lesson shows out of the live API documents.
// No React and no fetch: the pages fetch through server-api.ts and pass the data in.

import type { BacktestPeriod, BacktestReport, EventStudy, StudyResult } from "../api";
import { expectedMaxFactor, psrFromStats, type SharpeInputs } from "./stats";

/** Fixed locale and timezone so server and browser render the same date. "Oct 15, 2026". */
export function dateLabel(iso: string | null | undefined): string {
  if (!iso) return "unknown date";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

/** ISO date (YYYY-MM-DD) of a timestamp, for JSON-LD and dateModified. */
export function isoDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
}

export function findRow(study: EventStudy | null, signal: string, bucket: string, horizon: number): StudyResult | undefined {
  return study?.results.find((r) => r.signal === signal && r.bucket === bucket && r.horizon_days === horizon);
}

/**
 * Trading days between two ISO dates, inclusive: weekdays x 252/261 (about 9 US market holidays a year).
 * An estimate: the backtest report does not publish the exact number of daily returns.
 */
export function estimateTradingDays(startIso: string, endIso: string): number {
  const start = Date.parse(`${startIso.slice(0, 10)}T00:00:00Z`);
  const end = Date.parse(`${endIso.slice(0, 10)}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 0;
  let weekdays = 0;
  for (let t = start; t <= end; t += 86_400_000) {
    const dow = new Date(t).getUTCDay();
    if (dow !== 0 && dow !== 6) weekdays += 1;
  }
  return Math.round((weekdays * 252) / 261);
}

export interface DsrPrefill {
  period: string;
  label: string;
  inputs: SharpeInputs;
  trials: number;
  /** Standard deviation of the trial Sharpes, backed out of the report's luck benchmark. */
  sdTrials: number;
  luckSharpe: number | null;
  reportPsr: number;
  reportDsr: number | null;
  recomputedPsr: number;
  recomputedDsr: number;
}

/**
 * Calculator inputs for one backtest period. The report publishes the annualized Sharpe, skew and
 * kurtosis (rounded to 2 decimals), the number of trials and the luck benchmark luck_sharpe_<key>
 * = sd(trial Sharpes) x expectedMaxFactor(trials). The number of daily returns is estimated from
 * the period's first and last trading dates (equity points - 1).
 */
export function dsrPrefill(report: BacktestReport, key: string): DsrPrefill | null {
  const p: BacktestPeriod | undefined = report.periods[key];
  if (!p?.metrics.start || !p.metrics.end) return null;
  const m = p.metrics;
  const n = Math.max(0, estimateTradingDays(m.start!, m.end!) - 1);
  const inputs: SharpeInputs = { sharpeAnnual: m.sharpe, n, skew: m.skew, kurt: m.kurtosis };
  const trials = Number(report.overfitting?.trials ?? 0);
  const luck = report.overfitting?.[`luck_sharpe_${key}`];
  const luckSharpe = typeof luck === "number" ? luck : null;
  const factor = expectedMaxFactor(trials);
  const sdTrials = luckSharpe !== null && factor > 0 ? luckSharpe / factor : 0;
  const reportDsr = report.overfitting?.[`dsr_${key}`];
  return {
    period: key,
    label: p.period.label,
    inputs,
    trials,
    sdTrials,
    luckSharpe,
    reportPsr: m.psr,
    reportDsr: typeof reportDsr === "number" ? reportDsr : null,
    recomputedPsr: psrFromStats(inputs, 0),
    recomputedDsr: psrFromStats(inputs, luckSharpe ?? 0),
  };
}

/** "Historical" for measured past data, "Hypothetical" for simulated trading. */
export type LiveKind = "historical" | "hypothetical" | "historical, hypothetical";
