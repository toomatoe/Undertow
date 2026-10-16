"use client";

import type { BacktestPeriod, BacktestReport } from "@/lib/api";
import { fmtNum, pct, pctAbs, pctOr } from "@/lib/format";

import { PERIOD_TITLES, Signed } from "./parts";

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fee = (v: number) => `${pctAbs(v, 0)}/yr`;

export function breakevenText(be: number | null, maxApr: number | null): string {
  if (be === null) return `Never breaks even in the range tested${maxApr !== null ? ` (up to ${fee(maxApr)})` : ""}.`;
  if (be <= 0) return "Loses money even with free borrow.";
  return `Breaks even at a borrow fee of about ${fee(be)}.`;
}

/** Which row of the sensitivity grid is closest to a given fee. */
function nearest(rows: { borrow_apr: number }[], target: number | null): number {
  if (target === null || !rows.length) return -1;
  let best = 0;
  rows.forEach((r, i) => {
    if (Math.abs(r.borrow_apr - target) < Math.abs(rows[best].borrow_apr - target)) best = i;
  });
  return best;
}

function PeriodTable({ pkey, p, assumed, today }: { pkey: string; p: BacktestPeriod; assumed: number | null; today: number | null }) {
  const bs = p.borrow_sensitivity;
  if (!bs?.rows?.length) return null;
  const rows = [...bs.rows].sort((a, b) => a.borrow_apr - b.borrow_apr);
  const iAssumed = nearest(rows, assumed);
  const iToday = nearest(rows, today);
  const maxApr = rows[rows.length - 1].borrow_apr;
  return (
    <div>
      <h3 className="bt-sub">
        {pkey}: {PERIOD_TITLES[pkey]?.title ?? p.period.label}
      </h3>
      <p className={`small bt-breakeven ${bs.breakeven_apr !== null && bs.breakeven_apr > 0 ? "" : "bad"}`}>
        <strong>{breakevenText(bs.breakeven_apr, maxApr)}</strong>
      </p>
      <div className="table-scroll">
        <table className="data bt-num">
          <thead>
            <tr>
              <th>Borrow fee</th>
              <th>Total return</th>
              <th>CAGR</th>
              <th>Sharpe</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.borrow_apr} className={i === iAssumed ? "row-sig" : ""}>
                <td>{fee(r.borrow_apr)}</td>
                <td>
                  <Signed v={r.total_return} fmt={(v) => pct(v)} />
                </td>
                <td>
                  <Signed v={r.cagr} fmt={(v) => pct(v)} />
                </td>
                <td>{fmtNum(r.sharpe)}</td>
                <td className="bt-note">
                  {[i === iAssumed ? "← assumed" : "", i === iToday ? "← ≈ IBKR median today" : ""].filter(Boolean).join(" ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function BorrowFees({ report, periods }: { report: BacktestReport; periods: [string, BacktestPeriod][] }) {
  const bc = report.borrow_check;
  const assumed = num(bc.assumed_fee) ?? num(report.base_config.borrow_apr);
  const today = bc.available ? num(bc.fee_median) : null;
  return (
    <>
      <div className="bt-borrow">
        <div className="bt-borrow-today">
          <h3 className="bt-sub">Today&apos;s borrow on IBKR</h3>
          {bc.available ? (
            <>
              <table className="data bt-num">
                <thead>
                  <tr>
                    <th />
                    <th>Today</th>
                    <th>Assumed</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Median fee</td>
                    <td>{pctOr(num(bc.fee_median), 0, false)}</td>
                    <td rowSpan={3}>{pctOr(assumed, 0, false)}</td>
                  </tr>
                  <tr>
                    <td>75th percentile</td>
                    <td>{pctOr(num(bc.fee_p75), 0, false)}</td>
                  </tr>
                  <tr>
                    <td>90th percentile</td>
                    <td>{pctOr(num(bc.fee_p90), 0, false)}</td>
                  </tr>
                  <tr>
                    <td>Borrowable</td>
                    <td>{pctOr(num(bc.borrowable_share), 0, false)}</td>
                    <td>{pctOr(num(bc.assumed_availability), 0, false)}</td>
                  </tr>
                </tbody>
              </table>
              <p className="muted small">
                {String(bc.issuers_checked ?? "—")} recent nano-cap issuers checked, {String(bc.on_ibkr_list ?? "—")} on IBKR&apos;s list.{" "}
                {typeof bc.note === "string" ? bc.note : ""} Snapshot history: {String(bc.days ?? 0)} day(s)
                {bc.last ? `, latest ${String(bc.last)}` : ""}.
              </p>
            </>
          ) : (
            <p className="muted small">
              No IBKR borrow snapshot archived yet ({String(bc.days ?? 0)} day(s)). The API saves one after each ingest cycle.
            </p>
          )}
        </div>
        <div className="bt-two">
          {periods.map(([k, p]) => (
            <PeriodTable key={k} pkey={k} p={p} assumed={assumed} today={today} />
          ))}
        </div>
      </div>
    </>
  );
}
