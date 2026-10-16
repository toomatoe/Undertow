"use client";

import { useMemo, useState } from "react";

import type { JournalSummary, JournalSummaryRow } from "@/lib/api";
import { pctOr } from "@/lib/format";

import { Abn, DirMark, sizeShort, sizeTitle } from "./parts";

const MIN_N = 3; // default filter: signals with at least this many entries
const MIN_RESULTS = 5; // fewer completed results than this at a horizon = "too early"
const HORIZONS = [5, 20] as const;

function HorizonCells({ r, h }: { r: JournalSummaryRow; h: 5 | 20 }) {
  const n = r[`n_${h}`];
  const expected = r[`expected_${h}`];
  const exp = (
    <td className="tr-exp">
      <Abn v={expected} />
    </td>
  );
  if (n < MIN_RESULTS) {
    return (
      <>
        <td colSpan={3} className="tr-early" title={`${n} of ${MIN_RESULTS} results needed before we show a live average`}>
          Too early ({n}/{MIN_RESULTS})
        </td>
        {exp}
      </>
    );
  }
  return (
    <>
      <td className="tr-hstart">
        <Abn v={r[`mean_${h}`]} /> <span className="muted">({n})</span>
      </td>
      <td>
        <Abn v={r[`median_${h}`]} />
      </td>
      <td>{pctOr(r[`hit_${h}`], 0, false)}</td>
      {exp}
    </>
  );
}

export default function LiveVsExpected({ summary, error }: { summary: JournalSummary | null; error: string | null }) {
  const [showAll, setShowAll] = useState(false);
  const sorted = useMemo(() => [...(summary?.rows ?? [])].sort((a, b) => b.n - a.n || a.label.localeCompare(b.label)), [summary]);
  const rows = showAll ? sorted : sorted.filter((r) => r.n >= MIN_N);
  const hidden = sorted.length - sorted.filter((r) => r.n >= MIN_N).length;

  return (
    <section className="panel">
      <div className="panel-head bt-wrap">
        <h2>Live results vs what the backtest expected</h2>
        {summary && hidden > 0 && (
          <label className="check small">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            Show all signals ({hidden} with fewer than {MIN_N} filings hidden)
          </label>
        )}
      </div>
      <p className="muted small">
        Each row is one kind of filing in one company size. &quot;Live&quot; is the average move versus IWM for filings recorded here; &quot;Edge
        Lab&quot; is what the historical event study found for the same signal and size. Hit rate is the share that moved the expected way (▼
        signals: fell versus IWM; ▲ and ◆ signals: rose). We wait for {MIN_RESULTS} results before showing a live average.
        {summary?.marked && <> Prices last updated {new Date(`${summary.marked}T12:00:00`).toLocaleDateString()}.</>}
      </p>
      {error ? (
        <p className="error small">Couldn&apos;t load the summary: {error}</p>
      ) : !summary ? (
        <p className="muted small">Loading…</p>
      ) : !sorted.length ? (
        <p className="muted small">No signals recorded yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="data tr-table tr-summary">
            <thead>
              <tr>
                <th rowSpan={2}>Signal</th>
                <th rowSpan={2}>Size</th>
                <th rowSpan={2}>Filings</th>
                {HORIZONS.map((h) => (
                  <th key={h} colSpan={4} className="tr-hstart tr-group">
                    After {h} trading days
                  </th>
                ))}
              </tr>
              <tr>
                {HORIZONS.map((h) => (
                  <SubHeaders key={h} />
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.signal}-${r.bucket}`}>
                  <td className="tr-text">
                    <DirMark d={r.direction} /> {r.label}
                  </td>
                  <td title={sizeTitle(r.bucket)}>{sizeShort(r.bucket)}</td>
                  <td>{r.n}</td>
                  <HorizonCells r={r} h={5} />
                  <HorizonCells r={r} h={20} />
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={11} className="muted">
                    No signal has {MIN_N} or more filings yet. Tick &quot;Show all&quot; to see every one.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        <DirMark d="-" /> expected to fall · <DirMark d="+" /> expected to rise · <DirMark d="?" /> direction unclear. ▲/▼ on numbers mark moves
        above or below IWM. A dash under Edge Lab means the study had too few past examples for that signal and size.
      </p>
    </section>
  );
}

function SubHeaders() {
  return (
    <>
      <th className="tr-hstart">Live avg (n)</th>
      <th>Median</th>
      <th>Hit rate</th>
      <th>Edge Lab</th>
    </>
  );
}
