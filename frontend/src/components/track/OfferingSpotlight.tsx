"use client";

import Link from "next/link";
import { useMemo } from "react";

import type { JournalEntry, JournalSummary } from "@/lib/api";
import { formatBorrowFee, pct } from "@/lib/format";

import { Abn, formatDay, formatFiled, StatusBadge } from "./parts";
import RunningMeanChart, { type RunningPoint } from "./RunningMeanChart";

const SIGNAL = "offering_priced";
const BUCKET = "nano";

export default function OfferingSpotlight({ entries, summary }: { entries: JournalEntry[]; summary: JournalSummary | null }) {
  const rows = useMemo(() => entries.filter((e) => e.primary_signal === SIGNAL && e.size_bucket === BUCKET), [entries]);
  const points = useMemo<RunningPoint[]>(() => {
    const done = rows
      .filter((e) => e.abn_20 !== null)
      .sort((a, b) => (a.entry_date ?? "").localeCompare(b.entry_date ?? "") || a.filed_at.localeCompare(b.filed_at));
    let sum = 0;
    return done.map((e, i) => {
      sum += e.abn_20 as number;
      return { label: `${e.ticker}, ${formatDay(e.entry_date)}`, value: sum / (i + 1), n: i + 1 };
    });
  }, [rows]);
  const expected = summary?.rows.find((r) => r.signal === SIGNAL && r.bucket === BUCKET)?.expected_20 ?? null;
  const last = points[points.length - 1];

  return (
    <section className="panel tr-spotlight">
      <h2>Spotlight: nano-cap priced offerings</h2>
      <p className="small">
        When a company under $50M sells new shares at a set price, the stock has historically tended to drift down afterwards. This is the
        signal the backtest is built on, so it&apos;s the one to watch.
        {expected !== null && (
          <>
            {" "}
            The Edge Lab expects an average of <strong>{pct(expected)}</strong> versus IWM after 20 trading days.
          </>
        )}
      </p>

      {points.length >= 2 ? (
        <>
          <p className="muted small bt-chart-title">
            Running average 20-day result versus IWM, adding one filing at a time as each completes. Latest: {last.n} results, average{" "}
            {last.value > 0 ? "▲" : "▼"} {pct(last.value)}.
          </p>
          <RunningMeanChart points={points} reference={expected} />
        </>
      ) : (
        <p className="tr-collecting">
          <span aria-hidden="true">◔</span> Collecting data: first 20-day results land about 4 weeks after the first filing.
          {points.length === 1 && <> One result so far: {pct(points[0].value)}.</>}
        </p>
      )}

      {rows.length ? (
        <div className="table-scroll">
          <table className="data tr-table">
            <thead>
              <tr>
                <th>Filed</th>
                <th>Ticker</th>
                <th>Borrow fee</th>
                <th>Entry</th>
                <th>1d</th>
                <th>5d</th>
                <th>20d</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td>
                    <a href={e.filing_url} target="_blank" rel="noreferrer" className="bt-link" title={e.title}>
                      {formatFiled(e.filed_at)}
                    </a>
                  </td>
                  <td>
                    <Link href={`/ticker/${encodeURIComponent(e.ticker)}`} className="bt-link">
                      {e.ticker}
                    </Link>
                  </td>
                  <td>{formatBorrowFee(e.borrow_fee)}</td>
                  <td>{formatDay(e.entry_date)}</td>
                  <td>
                    <Abn v={e.abn_1} />
                  </td>
                  <td>
                    <Abn v={e.abn_5} />
                  </td>
                  <td>
                    <Abn v={e.abn_20} />
                  </td>
                  <td>
                    <StatusBadge status={e.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted small">No nano-cap priced offerings recorded yet.</p>
      )}
    </section>
  );
}
