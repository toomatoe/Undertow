"use client";

// Client module because it uses helpers from track/parts (a client module). It has no hooks and is
// server-rendered with the issue passed in as props. Numbers and dates use fixed locale/timezone so
// the server HTML and the browser render match.
import Link from "next/link";

import { Signed } from "@/components/backtest/parts";
import { DirMark, sizeShort, sizeTitle } from "@/components/track/parts";
import type { NewsletterDilution, NewsletterFiling, NewsletterIssue, NewsletterRunway } from "@/lib/api";
import { formatMoney, pct } from "@/lib/format";

import { dayLabel, etTime, weekLabel } from "./format";

const SEV_WORD: Record<number, string> = { 3: "High severity", 2: "Medium severity", 1: "Low severity" };

function Tile({ name, value }: { name: string; value: number }) {
  return (
    <div className="tile">
      <span className="muted small">{name}</span>
      <strong>{value.toLocaleString("en-US")}</strong>
    </div>
  );
}

function FilingItem({ f }: { f: NewsletterFiling }) {
  const ev = f.evidence;
  return (
    <li className="nl-item">
      <div className="nl-item-head">
        <Link href={`/ticker/${encodeURIComponent(f.ticker)}`} className="nl-ticker">
          {f.ticker}
        </Link>
        <span>{f.company}</span>
        <span className={`nl-sev nl-sev-${f.severity}`}>{SEV_WORD[f.severity] ?? ""}</span>
      </div>
      <div className="muted small nl-meta">
        <span title={sizeTitle(f.size)}>{sizeShort(f.size)} cap</span> · float {formatMoney(f.public_float)} · Form {f.form ?? "n/a"} · filed {etTime(f.filed_at)} ·{" "}
        <a href={f.url} target="_blank" rel="noreferrer" className="nl-link">
          filing
        </a>
      </div>
      <ul className="nl-signals">
        {f.signals.map((s) => (
          <li key={s.code}>
            <DirMark d={s.direction} /> {s.label}
          </li>
        ))}
      </ul>
      {ev && ev.mean_abnormal !== null && (
        <p className="nl-evidence small">
          <span className="muted">Historical, hypothetical:</span> past {f.size} caps after “{ev.label}” moved{" "}
          <Signed v={ev.mean_abnormal} fmt={(x) => pct(x)} /> on average vs the index over {ev.horizon_days} trading days
          {ev.excess_vs_baseline !== null && (
            <>
              {" "}
              (<Signed v={ev.excess_vs_baseline} fmt={(x) => pct(x)} /> vs ordinary days)
            </>
          )}
          , n={ev.n}, {ev.significant ? "significant after multiple-testing correction" : "not statistically significant"}.
        </p>
      )}
    </li>
  );
}

function runwayText(rw: NewsletterRunway | null): string {
  if (!rw) return "not looked up";
  if (rw.stale && rw.cash_as_of) return `latest reported cash is from ${dayLabel(rw.cash_as_of)}, too old to estimate`;
  if (rw.status === "burning" && rw.months !== null)
    return `about ${rw.months.toFixed(1)} months of operating burn${rw.cash_as_of ? ` as of ${dayLabel(rw.cash_as_of)}` : ""}, before any later raise`;
  if (rw.status === "cash_flow_positive") return "operating cash flow positive (trailing 12 months)";
  return "not reported in XBRL";
}

function DilutionItem({ d }: { d: NewsletterDilution }) {
  return (
    <li className="nl-item">
      <div className="nl-item-head">
        <Link href={`/ticker/${encodeURIComponent(d.ticker)}`} className="nl-ticker">
          {d.ticker}
        </Link>
        <span>{d.company}</span>
        <span className="muted small">
          {sizeShort(d.size)} cap · float {formatMoney(d.public_float)}
        </span>
      </div>
      <div className="small">{d.reasons.join("; ")}.</div>
      <div className="small">
        <span className="muted">Runway:</span> {runwayText(d.runway)}
      </div>
      <div className="muted small nl-meta">
        Filings:{" "}
        {d.filings.map((f, i) => (
          <span key={f.url}>
            {i > 0 && "; "}
            <a href={f.url} target="_blank" rel="noreferrer" className="nl-link">
              {f.form ?? "filing"}
            </a>{" "}
            {etTime(f.filed_at)}
          </span>
        ))}
      </div>
    </li>
  );
}

export default function IssueView({ issue }: { issue: NewsletterIssue }) {
  const h = issue.headline;
  const tr = issue.track_record;
  const note = issue.research_note;
  return (
    <article className="nl-issue">
      <header className="nl-issue-head">
        <h2>{weekLabel(issue)}</h2>
        <span className="muted small">
          Issue {issue.id}
          {issue.partial ? (
            <>
              {" · "}
              <strong className="nl-preview-tag">Preview: week in progress</strong>, data through {etTime(issue.data_through)}
            </>
          ) : (
            <> · generated {dayLabel(issue.generated_at)}</>
          )}
        </span>
        {issue.coverage_note && <p className="hint">{issue.coverage_note}</p>}
      </header>

      <section className="panel">
        <h2>This week in numbers</h2>
        <div className="tiles nl-tiles">
          <Tile name="Signal filings" value={h.signal_filings} />
          <Tile name="High severity" value={h.by_severity["3"]} />
          <Tile name="Medium severity" value={h.by_severity["2"]} />
          <Tile name="Dilution watch" value={h.dilution_watch} />
          <Tile name="Serious halts" value={h.serious_halts} />
        </div>
        <p className="muted small">
          {h.companies} small-cap companies · nano {h.by_size.nano} · micro {h.by_size.micro} · small {h.by_size.small} · low severity{" "}
          {h.by_severity["1"]}
        </p>
      </section>

      <section className="panel">
        <h2>Top filings this week</h2>
        {issue.top_filings.length === 0 ? (
          <p className="muted small">No high- or medium-severity signal filings from small caps this week.</p>
        ) : (
          <ul className="nl-list">
            {issue.top_filings.map((f) => (
              <FilingItem key={f.article_id} f={f} />
            ))}
          </ul>
        )}
        {issue.top_filings_total > issue.top_filings.length && (
          <p className="muted small">Plus {issue.top_filings_total - issue.top_filings.length} more high- or medium-severity filings.</p>
        )}
      </section>

      <section className="panel">
        <h2>Dilution watch</h2>
        <p className="muted small">Companies with 2+ offering-type filings this week, or a priced offering with reported cash runway under 6 months.</p>
        {issue.dilution_watch.length === 0 ? (
          <p className="muted small">None this week.</p>
        ) : (
          <ul className="nl-list">
            {issue.dilution_watch.map((d) => (
              <DilutionItem key={d.ticker} d={d} />
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>Serious trading halts</h2>
        {issue.serious_halts.length === 0 ? (
          <p className="muted small">No news-pending or regulatory halts for small caps this week.</p>
        ) : (
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Company</th>
                  <th>Size</th>
                  <th>Reason</th>
                  <th>Halted</th>
                  <th>Resumed</th>
                </tr>
              </thead>
              <tbody>
                {issue.serious_halts.map((x) => (
                  <tr key={`${x.symbol}-${x.halted_at}`}>
                    <td>
                      <strong>{x.symbol}</strong>
                    </td>
                    <td className="tr-text">{x.name}</td>
                    <td title={sizeTitle(x.size)}>{sizeShort(x.size)}</td>
                    <td className="tr-text">
                      {x.reason} ({x.reason_code})
                    </td>
                    <td>{etTime(x.halted_at)}</td>
                    <td>{x.resumed_at ? etTime(x.resumed_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {issue.serious_halts_total > issue.serious_halts.length && (
          <p className="muted small">Plus {issue.serious_halts_total - issue.serious_halts.length} more.</p>
        )}
      </section>

      <section className="panel">
        <h2>Track record update</h2>
        <p className="muted small">
          Simulated forward tracking of every signal as filed; no trades. <Link href="/track-record" className="nl-link">Full track record</Link>
        </p>
        {tr.collecting ? (
          <p className="small">
            Still collecting: {tr.collecting.recorded.toLocaleString("en-US")} signals recorded
            {tr.collecting.first_due && <>, first 20-day results due ~{dayLabel(tr.collecting.first_due)}</>}. Groups are shown once they have{" "}
            {tr.min_n}+ 20-day results.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Size</th>
                  <th>n (20d)</th>
                  <th>Live mean vs IWM</th>
                  <th>Median</th>
                  <th>Hit rate</th>
                  <th>Edge Lab historical</th>
                </tr>
              </thead>
              <tbody>
                {tr.rows.map((r) => (
                  <tr key={`${r.signal}-${r.bucket}`}>
                    <td className="tr-text">
                      <DirMark d={r.direction} /> {r.label}
                    </td>
                    <td>{sizeShort(r.bucket)}</td>
                    <td>{r.n_20}</td>
                    <td>
                      <Signed v={r.mean_20} fmt={(x) => pct(x)} />
                    </td>
                    <td>
                      <Signed v={r.median_20} fmt={(x) => pct(x)} />
                    </td>
                    <td>{r.hit_20 !== null && r.direction !== "?" ? `${Math.round(r.hit_20 * 100)}%` : "—"}</td>
                    <td>
                      <Signed v={r.expected_20} fmt={(x) => pct(x)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {note && (
        <section className="panel">
          <h2>Research note</h2>
          <p className="muted small">
            From our hypothetical backtest{note.strategy && note.report_date && <> (“{note.strategy}”, report of {dayLabel(note.report_date)})</>}. Simulated
            results, not real trading. <Link href="/backtest" className="nl-link">Full backtest</Link>
          </p>
          <p className="nl-note">{note.text}</p>
        </section>
      )}

      <footer className="nl-foot muted small">
        <p>
          How every number is produced: <Link href="/methodology">Methodology</Link> · <Link href="/lab">Edge Lab</Link> ·{" "}
          <Link href="/legal/disclaimer">Disclaimer</Link>
        </p>
        {issue.disclaimer.map((p) => (
          <p key={p.slice(0, 40)}>{p}</p>
        ))}
      </footer>
    </article>
  );
}
