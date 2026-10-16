"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { BacktestPeriod, BacktestTrade } from "@/lib/api";
import { formatUsd, pct } from "@/lib/format";

import { EXIT_LABELS, label, Signed } from "./parts";

const PAGE = 50;

const CSV_COLUMNS: (keyof BacktestTrade)[] = [
  "ticker",
  "company",
  "form",
  "filed",
  "filing_url",
  "public_float",
  "entry_date",
  "exit_date",
  "days_held",
  "entry_price",
  "exit_move",
  "notional",
  "short_pnl",
  "hedge_pnl",
  "costs",
  "borrow",
  "net_pnl",
  "net_return",
  "exit_reason",
];

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function downloadCsv(trades: BacktestTrade[], name: string) {
  const rows = [CSV_COLUMNS.join(","), ...trades.map((t) => CSV_COLUMNS.map((c) => csvCell(t[c])).join(","))];
  const url = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

type Sort = "date_desc" | "date_asc" | "pnl_desc" | "pnl_asc";

export default function TradeLog({ periods }: { periods: Record<string, BacktestPeriod> }) {
  const keys = Object.keys(periods).sort();
  const [pkey, setPkey] = useState(keys[0] ?? "A");
  const [reason, setReason] = useState("");
  const [sort, setSort] = useState<Sort>("date_desc");
  const [page, setPage] = useState(0);

  const all = useMemo(() => periods[pkey]?.trades ?? [], [periods, pkey]);
  const reasons = useMemo(() => [...new Set(all.map((t) => t.exit_reason))].sort(), [all]);
  const rows = useMemo(() => {
    const out = reason ? all.filter((t) => t.exit_reason === reason) : [...all];
    const cmp: Record<Sort, (a: BacktestTrade, b: BacktestTrade) => number> = {
      date_desc: (a, b) => b.entry_date.localeCompare(a.entry_date),
      date_asc: (a, b) => a.entry_date.localeCompare(b.entry_date),
      pnl_desc: (a, b) => b.net_pnl - a.net_pnl,
      pnl_asc: (a, b) => a.net_pnl - b.net_pnl,
    };
    return out.sort(cmp[sort]);
  }, [all, reason, sort]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const current = Math.min(page, pages - 1);
  const shown = rows.slice(current * PAGE, current * PAGE + PAGE);

  return (
    <section className="panel" id="trades">
      <div className="panel-head bt-wrap">
        <h2>Trade log</h2>
        <div className="bt-controls">
          <div className="seg" role="group" aria-label="Period">
            {keys.map((k) => (
              <button
                key={k}
                className={k === pkey ? "on" : ""}
                onClick={() => {
                  setPkey(k);
                  setReason("");
                  setPage(0);
                }}
              >
                Period {k}
              </button>
            ))}
          </div>
          <select
            aria-label="Exit reason"
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All exits</option>
            {reasons.map((r) => (
              <option key={r} value={r}>
                {label(EXIT_LABELS, r)}
              </option>
            ))}
          </select>
          <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="date_desc">Newest first</option>
            <option value="date_asc">Oldest first</option>
            <option value="pnl_desc">Biggest gain first</option>
            <option value="pnl_asc">Biggest loss first</option>
          </select>
          <button className="btn" onClick={() => downloadCsv(rows, `backtest_trades_${pkey}${reason ? `_${reason}` : ""}.csv`)} disabled={!rows.length}>
            Download CSV
          </button>
        </div>
      </div>
      <p className="muted small">
        Every simulated short in period {pkey}. &quot;Move&quot; is the stock&apos;s change from entry to exit: down is good for a
        short. Net P&amp;L includes the IWM hedge, trading costs and borrow fees.
      </p>
      <div className="table-scroll">
        <table className="data bt-trades">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Filed</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Days</th>
              <th>Entry price</th>
              <th>Move</th>
              <th>Net P&amp;L</th>
              <th>Net return</th>
              <th>Exit reason</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((t, i) => (
              <tr key={`${t.ticker}-${t.entry_date}-${i}`}>
                <td>
                  <Link href={`/ticker/${encodeURIComponent(t.ticker)}`} className="bt-link" title={t.company}>
                    {t.ticker}
                  </Link>
                </td>
                <td>
                  <a href={t.filing_url} target="_blank" rel="noreferrer" className="bt-link" title={`${t.form} on EDGAR`}>
                    {t.filed.slice(0, 10)} {t.form}
                  </a>
                </td>
                <td>{t.entry_date}</td>
                <td>{t.exit_date}</td>
                <td>{t.days_held}</td>
                <td>${t.entry_price < 1 ? t.entry_price.toFixed(3) : t.entry_price.toFixed(2)}</td>
                <td>{pct(t.exit_move)}</td>
                <td>
                  <Signed v={t.net_pnl} fmt={(v) => formatUsd(v, true)} />
                </td>
                <td>
                  <Signed v={t.net_return} fmt={(v) => pct(v)} />
                </td>
                <td>{label(EXIT_LABELS, t.exit_reason)}</td>
              </tr>
            ))}
            {!shown.length && (
              <tr>
                <td colSpan={10} className="muted">
                  No trades.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="bt-pager small muted">
        <span>
          {rows.length ? `${current * PAGE + 1}–${Math.min(rows.length, (current + 1) * PAGE)} of ${rows.length}` : "0"} trades
        </span>
        <button className="btn" onClick={() => setPage(current - 1)} disabled={current === 0}>
          ← Prev
        </button>
        <span>
          Page {current + 1} / {pages}
        </span>
        <button className="btn" onClick={() => setPage(current + 1)} disabled={current >= pages - 1}>
          Next →
        </button>
      </div>
    </section>
  );
}
