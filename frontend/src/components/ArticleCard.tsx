import Link from "next/link";

import type { Article, Evidence } from "@/lib/api";
import { formatScore, humanize, pct, sentimentClass, SOURCE_LABELS, timeAgo } from "@/lib/format";


export const FORWARD_TEST_LABEL = "Forward test of pre-registered finding";

/** e.g. "+1.66% vs ordinary days over 5d, n=662, clustered t 3.29 (in-sample, hypothetical)", from the evidence fields. */
function ForwardTestEvidenceLine({ ev }: { ev: Evidence }) {
  const drift =
    ev.excess_vs_baseline !== null && ev.excess_vs_baseline !== undefined
      ? `${pct(ev.excess_vs_baseline, 2)} vs ordinary days`
      : `${pct(ev.mean_abnormal, 2)} vs index`;
  const t = ev.t_stat_clustered ?? ev.t_stat;
  return (
    <span
      className={`evidence ${ev.significant ? "sig" : ""}`}
      title={`Pre-registered insider study (${ev.study ?? "insider_purchases"}), in-sample result now being forward-tested live. Hypothetical, before any live results.`}
    >
      Past {ev.bucket} caps: {drift} over {ev.horizon_days}d, n={ev.n}, {ev.t_stat_clustered != null ? "clustered t" : "t"} {t.toFixed(2)}{" "}
      (in-sample, hypothetical)
    </span>
  );
}

function EvidenceLine({ ev }: { ev: Evidence }) {
  if (ev.forward_test) return <ForwardTestEvidenceLine ev={ev} />;
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
  const forwardTest =
    a.forward_test === true ||
    a.signals?.some((s) => s.forward_test === true) === true;
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
        {forwardTest && (
          <span
            className="badge event"
            title="Live forward test of a finding from a separate pre-registered study. Historical figures are in-sample and hypothetical."
          >
            {FORWARD_TEST_LABEL}
          </span>
        )}
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
