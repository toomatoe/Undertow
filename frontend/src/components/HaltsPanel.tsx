"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Halt } from "@/lib/api";

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function day(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Trading halts from the Nasdaq Trader feed. `symbol` scopes it to one ticker; otherwise small caps today. */
export default function HaltsPanel({ symbol, size = "nano,micro,small", hours = 24 }: { symbol?: string; size?: string; hours?: number }) {
  const [halts, setHalts] = useState<Halt[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPauses, setShowPauses] = useState(false);

  useEffect(() => {
    const load = () =>
      api
        .halts(symbol ? { symbol, hours: 24 * 365 } : { size, hours })
        .then(setHalts)
        .catch((e) => setError(String(e.message ?? e)));
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [symbol, size, hours]);

  const visible = (halts ?? []).filter((h) => showPauses || h.serious || symbol);
  const hidden = (halts ?? []).length - visible.length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{symbol ? "Trading halts" : "Halts today"}</h2>
        {!symbol && hidden > 0 && (
          <label className="check small">
            <input type="checkbox" checked={showPauses} onChange={(e) => setShowPauses(e.target.checked)} />
            {hidden} volatility pauses
          </label>
        )}
      </div>
      {error && <p className="error small">Halts unavailable.</p>}
      {halts && visible.length === 0 && (
        <p className="muted small">{symbol ? "No halts recorded for this ticker." : "No news or regulatory halts in small caps today."}</p>
      )}
      <ul className="halts">
        {visible.slice(0, symbol ? 20 : 12).map((h) => (
          <li key={h.symbol + h.halted_at} className={h.serious ? "serious" : ""}>
            <span className="halt-time" title={new Date(h.halted_at).toLocaleString()}>
              {symbol ? `${day(h.halted_at)} ` : ""}
              {time(h.halted_at)}
            </span>
            {!symbol && (
              <Link href={`/ticker/${h.symbol}`} className="halt-sym">
                {h.symbol}
              </Link>
            )}
            <span className="halt-reason" title={`${h.reason_code}: ${h.name}`}>
              {h.serious ? "⏸ " : ""}
              {h.reason}
            </span>
            <span className="muted small">{h.resumed_at ? `resumed ${time(h.resumed_at)}` : "halted"}</span>
          </li>
        ))}
      </ul>
      <p className="muted small">Source: Nasdaq Trader halt feed, checked every 30 seconds.</p>
    </section>
  );
}
