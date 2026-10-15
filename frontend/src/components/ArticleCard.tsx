import Link from "next/link";

import type { Article } from "@/lib/api";
import { formatScore, sentimentClass, SOURCE_LABELS, timeAgo } from "@/lib/format";

export default function ArticleCard({ article, fresh = false }: { article: Article; fresh?: boolean }) {
  const a = article;
  return (
    <article className={`card ${fresh ? "fresh" : ""}`}>
      <div className="card-meta">
        <span className={`badge src-${a.source}`}>{SOURCE_LABELS[a.source] ?? a.source}</span>
        <span>{a.source_name}</span>
        <span className="dot">·</span>
        <time dateTime={a.published_at} title={new Date(a.published_at).toLocaleString()}>
          {timeAgo(a.published_at)}
        </time>
        {a.event_type && <span className="badge event">{a.event_type}</span>}
        <span className={`sent ${sentimentClass(a.sentiment)}`} title={a.sentiment_label ?? "not scored"}>
          {formatScore(a.sentiment)}
        </span>
      </div>
      <a href={a.url} target="_blank" rel="noopener noreferrer" className="card-title">
        {a.title}
      </a>
      {a.ai_summary ? (
        <p className="card-summary">
          <span className="ai">AI</span> {a.ai_summary}
        </p>
      ) : (
        a.snippet && <p className="card-snippet">{a.snippet}</p>
      )}
      {a.tickers.length > 0 && (
        <div className="chips">
          {a.tickers.map((t) => (
            <Link key={t.symbol} href={`/ticker/${t.symbol}`} className="chip" title={`tagged via ${t.method}`}>
              ${t.symbol}
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}
