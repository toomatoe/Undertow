"use client";

import type { ReadinessGate } from "@/lib/api";
import { fmtNum, pctOr } from "@/lib/format";

export const PERIOD_TITLES: Record<string, { title: string; sub: string }> = {
  A: { title: "Out-of-sample: the honest test", sub: "The signal was never studied on these years" },
  B: { title: "Discovery period: where the signal was found", sub: "Expect this to look better than reality" },
};

export const EXIT_LABELS: Record<string, string> = {
  time: "Held to the end",
  stop_loss: "Stop-loss (price spiked)",
  recall: "Borrow recalled",
  data_ended: "Data ended (delisted or halted)",
};

export const SKIP_LABELS: Record<string, string> = {
  no_price_data: "No price data (often delisted names)",
  no_trading_after_filing: "No trading after the filing",
  already_short: "Already short this stock",
  max_positions: "Too many open positions",
  below_price_floor: "Price under the floor",
  illiquid: "Too little daily trading volume",
  no_borrow: "Shares not available to borrow (simulated)",
  position_too_small: "Position would be too small",
  gross_limit: "Total short exposure limit reached",
};

export const label = (map: Record<string, string>, key: string) => map[key] ?? key.replace(/_/g, " ");

/** A value with a direction marker so sign never depends on color alone. */
export function Signed({ v, fmt, invert = false }: { v: number | null | undefined; fmt: (v: number) => string; invert?: boolean }) {
  if (v === null || v === undefined || !Number.isFinite(v)) return <span className="muted">—</span>;
  const good = invert ? v < 0 : v > 0;
  const cls = v === 0 ? "dv-zero" : good ? "dv-pos" : "dv-neg";
  const mark = v === 0 ? "•" : v > 0 ? "▲" : "▼";
  return (
    <span className={`dv ${cls}`}>
      <span aria-hidden="true">{mark}</span> {fmt(v)}
    </span>
  );
}

const STATUS = {
  pass: { icon: "✓", text: "Pass" },
  fail: { icon: "✗", text: "Fail" },
  pending: { icon: "○", text: "Pending" },
} as const;

export function GateStatus({ status }: { status: ReadinessGate["status"] }) {
  const s = STATUS[status] ?? STATUS.pending;
  return (
    <span className={`gate gate-${status}`}>
      <span aria-hidden="true">{s.icon}</span> {s.text}
    </span>
  );
}

/** Readiness values are raw numbers: format them by what the gate measures. */
export function gateValue(g: ReadinessGate): string {
  const v = g.value;
  if (typeof v !== "number") return v === null || v === undefined ? "—" : String(v);
  const name = g.gate.toLowerCase();
  const thr = g.threshold.toLowerCase();
  if (name.includes("return") || thr.includes("return")) return pctOr(v);
  if (name.includes("drawdown") || thr.includes("%")) return pctOr(v, 1, false);
  if (name.includes("trades")) return v.toLocaleString();
  return fmtNum(v);
}

export function sharpeWord(s: number): string {
  if (s >= 1.5) return "strong";
  if (s >= 1) return "good";
  if (s >= 0.5) return "modest";
  if (s > 0) return "weak";
  return "negative: worse than doing nothing";
}
