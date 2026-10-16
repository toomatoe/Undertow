"use client";

import { useEffect, useRef, useState } from "react";

import { api, type Fundamentals } from "@/lib/api";
import { formatMoney, pct, pctAbs } from "@/lib/format";

function formatShares(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(n);
}

function runwayText(f: Fundamentals): { value: string; tone: string; note: string } {
  const r = f.runway;
  if (r.status === "cash_flow_positive") return { value: "Cash-flow positive", tone: "sent-pos", note: "Operating cash flow over the last 12 months was positive." };
  if (r.status === "unknown" || r.months == null) return { value: "Unknown", tone: "sent-none", note: "Not enough reported data to estimate." };
  const tone = r.months < 6 ? "sent-neg" : r.months < 12 ? "warn-text" : "sent-neu";
  return {
    value: `${r.months.toFixed(1)} months`,
    tone,
    note: `At ${formatMoney(r.monthly_burn ?? 0)}/month burn, cash runs out around ${r.runs_out_around ?? "?"} (before any new raise).`,
  };
}

/** `initialData` (fetched on the server) renders immediately and skips the client fetch for that symbol. */
export default function DilutionPanel({ symbol, initialData }: { symbol: string; initialData?: Fundamentals }) {
  const [data, setData] = useState<Fundamentals | null>(initialData ?? null);
  const [error, setError] = useState<string | null>(null);
  const seeded = useRef<string | null>(initialData ? symbol : null);

  useEffect(() => {
    if (seeded.current === symbol) return;
    seeded.current = null;
    setData(null);
    setError(null);
    api.fundamentals(symbol).then(setData).catch((e) => setError(String(e.message ?? e)));
  }, [symbol]);

  if (error) {
    return (
      <section className="panel">
        <h2>Dilution &amp; runway</h2>
        <p className="muted small">{error.startsWith("404") ? "No SEC company data for this ticker." : `SEC data unavailable (${error}).`}</p>
      </section>
    );
  }
  if (!data) {
    return (
      <section className="panel">
        <h2>Dilution &amp; runway</h2>
        <p className="muted small">Loading SEC filings…</p>
      </section>
    );
  }

  const rw = runwayText(data);
  const change = data.share_change_1y;
  const si = data.short_interest;
  return (
    <section className="panel">
      <h2>Dilution &amp; runway</h2>
      <div className="tiles">
        <div className="tile">
          <span className="muted small">Cash runway</span>
          <strong className={rw.tone}>{rw.value}</strong>
          <span className="muted small">{rw.note}</span>
        </div>
        <div className="tile">
          <span className="muted small">Cash</span>
          <strong>{data.cash ? formatMoney(data.cash.value) : "—"}</strong>
          <span className="muted small">
            {data.cash
              ? `as of ${data.cash.as_of}${data.cash.short_term_investments ? ` (incl. ${formatMoney(data.cash.short_term_investments)} short-term investments)` : ""}`
              : "not reported"}
          </span>
        </div>
        <div className="tile">
          <span className="muted small">Share count, 1 year</span>
          <strong className={change && change.change > 0.1 ? "sent-neg" : undefined}>{change ? pct(change.change) : "—"}</strong>
          <span className="muted small">{change ? `${change.from} → ${change.to}` : "not enough history"}</span>
        </div>
        <div className="tile">
          <span className="muted small">Short interest</span>
          <strong className={si && (si.pct_of_shares_outstanding ?? 0) > 0.2 ? "warn-text" : undefined}>
            {si ? (si.pct_of_shares_outstanding != null ? pctAbs(si.pct_of_shares_outstanding) : formatShares(si.shares_short)) : "—"}
          </strong>
          <span className="muted small">
            {si
              ? `${formatShares(si.shares_short)} shares · ${si.days_to_cover ?? "?"} days to cover · FINRA ${si.date}`
              : "not reported by FINRA"}
          </span>
        </div>
        <div className="tile">
          <span className="muted small">Priced offerings, 12 months</span>
          <strong>{data.offerings_last_12m}</strong>
          <span className="muted small">
            {data.raises_since_cash_date > 0
              ? `${data.raises_since_cash_date} raise(s) after the cash date extend the runway`
              : "424B prospectuses filed"}
          </span>
        </div>
      </div>
      {data.dilution_filings.length > 0 && (
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                <th>Filed</th>
                <th>Form</th>
                <th>What it is</th>
              </tr>
            </thead>
            <tbody>
              {data.dilution_filings.slice(0, 15).map((f) => (
                <tr key={f.url + f.form}>
                  <td>{f.filed}</td>
                  <td>
                    <a href={f.url} target="_blank" rel="noopener noreferrer">
                      {f.form}
                    </a>
                  </td>
                  <td>{f.kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        From SEC filings: cash and trailing-12-month operating cash flow (XBRL), shares outstanding (cover pages), and offering-type filings
        over the last 3 years. Short interest from FINRA (twice monthly). Estimates are arithmetic on reported numbers, not forecasts.
      </p>
    </section>
  );
}
