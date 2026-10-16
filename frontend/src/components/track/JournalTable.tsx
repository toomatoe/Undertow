"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { JournalEntry } from "@/lib/api";
import { formatBorrowFee, formatPrice, humanize, SIZE_LABELS } from "@/lib/format";

import { Abn, DirMark, downloadCsv, formatDay, formatFiled, sizeShort, sizeTitle, STATUS_INFO, STATUS_ORDER, StatusBadge } from "./parts";

const PAGE = 50;

const CSV_HEADER = [
  "id",
  "filed_at",
  "ticker",
  "form",
  "title",
  "filing_url",
  "primary_signal",
  "signal_label",
  "signals",
  "direction",
  "severity",
  "size_bucket",
  "public_float",
  "borrow_fee",
  "borrow_available",
  "borrow_snapshot",
  "entry_date",
  "entry_price",
  "abn_1",
  "abn_5",
  "abn_20",
  "status",
] as const;

export default function JournalTable({ entries }: { entries: JournalEntry[] }) {
  const [signal, setSignal] = useState("");
  const [size, setSize] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);

  const signals = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of entries) m.set(e.primary_signal, e.signal_label);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [entries]);
  const sizes = useMemo(() => Object.keys(SIZE_LABELS).filter((b) => entries.some((e) => e.size_bucket === b)), [entries]);

  const rows = useMemo(
    () =>
      entries.filter(
        (e) => (!signal || e.primary_signal === signal) && (!size || e.size_bucket === size) && (!status || e.status === status),
      ),
    [entries, signal, size, status],
  );
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const current = Math.min(page, pages - 1);
  const shown = rows.slice(current * PAGE, current * PAGE + PAGE);
  const set = (fn: (v: string) => void) => (e: React.ChangeEvent<HTMLSelectElement>) => {
    fn(e.target.value);
    setPage(0);
  };

  const exportCsv = () =>
    downloadCsv(
      [...CSV_HEADER],
      rows.map((e) => CSV_HEADER.map((c) => e[c])),
      `quantdesk_track_record_${new Date().toISOString().slice(0, 10)}${signal ? `_${signal}` : ""}${size ? `_${size}` : ""}${status ? `_${status}` : ""}.csv`,
    );

  return (
    <section className="panel" id="journal">
      <div className="panel-head bt-wrap">
        <h2>Every signal, as recorded</h2>
        <div className="bt-controls">
          <select aria-label="Signal" value={signal} onChange={set(setSignal)}>
            <option value="">All signals</option>
            {signals.map(([code, lbl]) => (
              <option key={code} value={code}>
                {lbl}
              </option>
            ))}
          </select>
          <select aria-label="Company size" value={size} onChange={set(setSize)}>
            <option value="">All sizes</option>
            {sizes.map((b) => (
              <option key={b} value={b}>
                {SIZE_LABELS[b]}
              </option>
            ))}
          </select>
          <select aria-label="Status" value={status} onChange={set(setStatus)}>
            <option value="">Any status</option>
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {STATUS_INFO[s].short}
              </option>
            ))}
          </select>
          <button className="btn" onClick={exportCsv} disabled={!rows.length}>
            Download CSV
          </button>
        </div>
      </div>
      <p className="muted small">
        Newest first, times in your local time zone. 1d / 5d / 20d are the stock&apos;s move minus IWM&apos;s, measured from the entry price; ▲
        beat IWM, ▼ trailed it. Filtering by signal uses each filing&apos;s main signal.
      </p>
      <div className="table-scroll">
        <table className="data tr-table tr-journal">
          <thead>
            <tr>
              <th>Filed</th>
              <th>Ticker</th>
              <th>Filing</th>
              <th>Signal</th>
              <th>Size</th>
              <th title="IBKR borrow fee on the day the signal was recorded">Borrow fee</th>
              <th>Entry</th>
              <th>1d</th>
              <th>5d</th>
              <th>20d</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => {
              const extra = e.signals.filter((s) => s !== e.primary_signal);
              return (
                <tr key={e.id}>
                  <td className="tr-text">{formatFiled(e.filed_at)}</td>
                  <td className="tr-text">
                    <Link href={`/ticker/${encodeURIComponent(e.ticker)}`} className="bt-link">
                      {e.ticker}
                    </Link>
                  </td>
                  <td className="tr-title">
                    <a href={e.filing_url} target="_blank" rel="noreferrer" className="bt-link" title={e.title}>
                      {e.title}
                    </a>
                  </td>
                  <td className="tr-text">
                    <DirMark d={e.direction} /> {e.signal_label}
                    {extra.length > 0 && (
                      <span className="muted" title={`Also: ${extra.map(humanize).join(", ")}`}>
                        {" "}
                        +{extra.length} more
                      </span>
                    )}
                  </td>
                  <td title={sizeTitle(e.size_bucket)}>{sizeShort(e.size_bucket)}</td>
                  <td>{formatBorrowFee(e.borrow_fee)}</td>
                  <td>
                    {e.entry_date ? (
                      <>
                        {formatDay(e.entry_date)} <span className="muted">@ {formatPrice(e.entry_price)}</span>
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
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
              );
            })}
            {!shown.length && (
              <tr>
                <td colSpan={11} className="muted">
                  {entries.length ? "No entries match these filters." : "No signals recorded yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="bt-pager small muted">
        <span>{rows.length ? `${current * PAGE + 1}–${Math.min(rows.length, (current + 1) * PAGE)} of ${rows.length}` : "0"} entries</span>
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
