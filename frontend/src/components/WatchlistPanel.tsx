"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api, type TrendingTicker } from "@/lib/api";

export default function WatchlistPanel({ onChange }: { onChange?: () => void }) {
  const [items, setItems] = useState<TrendingTicker[]>([]);
  const [symbol, setSymbol] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.watchlist().then(setItems).catch(() => setItems([]));
  }, []);
  useEffect(load, [load]);

  const toggle = async (sym: string, on: boolean) => {
    setError(null);
    try {
      await api.watch(sym, on);
      setSymbol("");
      load();
      onChange?.();
    } catch (e) {
      setError(e instanceof Error && e.message.startsWith("404") ? `Unknown ticker ${sym}` : String(e));
    }
  };

  return (
    <section className="panel">
      <h2>Watchlist</h2>
      <form
        className="watch-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (symbol.trim()) toggle(symbol.trim().toUpperCase(), true);
        }}
      >
        <input placeholder="Add ticker" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
        <button className="btn" type="submit">
          Add
        </button>
      </form>
      {error && <p className="error small">{error}</p>}
      {items.length === 0 ? (
        <p className="muted small">Add tickers to filter signals to companies you follow.</p>
      ) : (
        <ul className="trending">
          {items.map((t) => (
            <li key={t.symbol}>
              <Link href={`/ticker/${t.symbol}`}>
                <strong>{t.symbol}</strong>
                <span className="muted ellipsis">{t.name}</span>
              </Link>
              <span className="count" title="Articles and filings in the last 7 days">
                {t.mentions}
              </span>
              <button className="icon-btn" onClick={() => toggle(t.symbol, false)} aria-label={`Remove ${t.symbol}`}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
