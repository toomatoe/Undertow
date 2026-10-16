"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import ArticleCard from "@/components/ArticleCard";
import DilutionPanel from "@/components/DilutionPanel";
import HaltsPanel from "@/components/HaltsPanel";
import { api, type TickerDetail } from "@/lib/api";
import { formatMoney, formatScore, sentimentClass, SIZE_LABELS } from "@/lib/format";

export default function TickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  const [data, setData] = useState<TickerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  useEffect(() => {
    setError(null);
    api.ticker(symbol, days).then(setData).catch((e) => setError(String(e.message ?? e)));
  }, [symbol, days]);

  const toggleWatch = async () => {
    if (!data) return;
    await api.watch(data.symbol, !data.on_watchlist);
    setData({ ...data, on_watchlist: !data.on_watchlist });
  };

  const maxMentions = Math.max(1, ...(data?.daily.map((d) => d.mentions) ?? [1]));

  return (
    <main className="page">
      <Link href="/" className="back">
        ← News
      </Link>
      {error && <p className="error">{error.startsWith("404") ? `No data for ${symbol.toUpperCase()} yet.` : error}</p>}
      {data && (
        <>
          <div className="ticker-head">
            <div>
              <h1>
                ${data.symbol}{" "}
                <button className={`star ${data.on_watchlist ? "on" : ""}`} onClick={toggleWatch} aria-pressed={data.on_watchlist}>
                  {data.on_watchlist ? "★ Watching" : "☆ Watch"}
                </button>
              </h1>
              <p className="muted">
                {data.name ?? "Unknown company"}
                {data.size_bucket && (
                  <>
                    {" · "}
                    <span title={`Public float ${formatMoney(data.public_float)} as of ${data.float_as_of}`}>
                      {SIZE_LABELS[data.size_bucket]}, float {formatMoney(data.public_float)}
                    </span>
                  </>
                )}
                {data.cik && (
                  <>
                    {" · "}
                    <a
                      href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${data.cik}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      SEC filings
                    </a>
                  </>
                )}
              </p>
            </div>
            <div className="stats">
              <div>
                <span className="muted small">Mentions</span>
                <strong>{data.mentions}</strong>
              </div>
              <div>
                <span className="muted small">Avg sentiment</span>
                <strong className={sentimentClass(data.avg_sentiment)}>{formatScore(data.avg_sentiment)}</strong>
              </div>
              <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Window">
                <option value={7}>7d</option>
                <option value={30}>30d</option>
                <option value={90}>90d</option>
              </select>
            </div>
          </div>

          {data.cik && <DilutionPanel symbol={data.symbol} />}
          <HaltsPanel symbol={data.symbol} />

          {data.daily.length > 0 && (
            <section className="panel">
              <h2>Coverage by day</h2>
              <div className="bars">
                {data.daily.map((d) => (
                  <div key={d.day} className="bar-col" title={`${d.day}: ${d.mentions} articles, sentiment ${formatScore(d.avg_sentiment)}`}>
                    <div className={`bar ${sentimentClass(d.avg_sentiment)}`} style={{ height: `${(d.mentions / maxMentions) * 100}%` }} />
                    <span className="bar-label">{d.day.slice(5)}</span>
                  </div>
                ))}
              </div>
              <p className="muted small">Bar height = article count. Color = average AI sentiment (grey when not scored).</p>
            </section>
          )}

          <section className="feed narrow">
            {data.articles.length === 0 && <p className="muted">No articles in this window.</p>}
            {data.articles.map((a) => (
              <ArticleCard key={a.id} article={a} />
            ))}
          </section>
        </>
      )}
    </main>
  );
}
