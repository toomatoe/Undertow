import Link from "next/link";

import type { Article, Evidence } from "@/lib/api";
import { formatScore, humanize, pct, sentimentClass, SOURCE_LABELS, timeAgo } from "@/lib/format";

function EvidenceLine({ ev }: { ev: Evidence }) {
  const verdict = ev.significant ? "edge after costs" : ev.mean_net > 0 ? "not significant" : "no edge after costs";
  return (
    <span className={`evidence ${ev.significant ? "sig" : ""}`} title={`t = ${ev.t_stat}, n = ${ev.n} past events`}>
      Past {ev.bucket} caps: {pct(ev.mean_abnormal)} vs index over {ev.horizon_days}d
      {ev.excess_vs_baseline !== null && ` (${pct(ev.excess_vs_baseline)} vs ordinary days)`}, n={ev.n} · {verdict}
    </span>
  );
}

export default function ArticleCard({ article, fresh = false }: { article: Article; fresh?: boolean }) {
  const a = article;
  return (
    <article className={`card ${fresh ? "fresh" : ""} ${a.severity ? `sev-${a.severity}` : ""}`}>
      <div className="card-meta">
        <span className={`badge src-${a.source}`}>{a.form ?? SOURCE_LABELS[a.source] ?? a.source}</span>
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
      {a.signals.length > 0 && (
        <div className="signals">
          {a.signals.map((s) => (
            <span key={s.code} className={`signal sev${s.severity}`} title={s.why}>
              <span className="dir">{s.direction === "-" ? "▼" : s.direction === "+" ? "▲" : "◆"}</span>
              {s.label}
            </span>
          ))}
          {a.ai_flags?.map((f) => (
            <span key={f} className="flag">
              {humanize(f)}
            </span>
          ))}
        </div>
      )}
      {a.ai_summary ? (
        <p className="card-summary">
          <span className="ai">AI</span> {a.ai_summary}
        </p>
      ) : (
        a.snippet && <p className="card-snippet">{a.snippet}</p>
      )}
      {a.evidence.map((ev) => (
        <EvidenceLine key={`${ev.signal}-${ev.bucket}`} ev={ev} />
      ))}
      {a.tickers.length > 0 && (
        <div className="chips">
          {a.tickers.map((t) => (
            <Link key={t.symbol} href={`/ticker/${t.symbol}`} className="chip" title={`tagged via ${t.method}`}>
              ${t.symbol}
              {t.size_bucket && <span className="size">{t.size_bucket}</span>}
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}
