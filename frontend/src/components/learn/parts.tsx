// Small presentational pieces shared by the Learn pages, the Lab and the widgets.
// No hooks and no "use client": they render on the server and inside client components alike.

import Link from "next/link";
import type { ReactNode } from "react";

import type { Reading, RepoRef } from "@/lib/learn/lessons";
import { repoHref } from "@/lib/learn/lessons";
import { dateLabel, type LiveKind } from "@/lib/learn/live";

import styles from "./learn.module.css";

/** "Historical · study generated Oct 15, 2026" / "Hypothetical · simulated in your browser". */
export function LiveTag({ kind, date, what }: { kind: LiveKind; date?: string | null; what?: string }) {
  const cls = kind === "historical" ? styles.tagHist : styles.tagHypo;
  const word = kind === "historical" ? "Historical" : kind === "hypothetical" ? "Hypothetical" : "Historical, hypothetical";
  return (
    <span className={`${styles.tag} ${cls}`}>
      {word}
      {date !== undefined && <> · {what ?? "generated"} {dateLabel(date)}</>}
      {date === undefined && what && <> · {what}</>}
    </span>
  );
}

/** Shown when a live document could not be loaded. The lesson itself still renders. */
export function ApiNote({ what, status }: { what: string; status: number }) {
  return (
    <p className={styles.note} role="note">
      {status === 404
        ? `The ${what} has not been run yet, so live Afterfile numbers are missing here. `
        : `Live Afterfile numbers (${what}) are unavailable right now${status ? ` (API answered ${status})` : " (API unreachable)"}. `}
      The explanation and the simulators below still work: they run on fixed formulas, not on the API.
    </p>
  );
}

export function Stat({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className={styles.stat}>
      <span>{label}</span>
      <strong>{value}</strong>
      {sub && <span>{sub}</span>}
    </div>
  );
}

/** Repo file + symbol, linked when NEXT_PUBLIC_REPO_URL is set, else a plain code path. */
export function RepoPath({ path }: { path: string }) {
  const href = repoHref(path);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer">
      <code>{path}</code>
    </a>
  ) : (
    <code>{path}</code>
  );
}

export function RepoRefs({ refs }: { refs: RepoRef[] }) {
  return (
    <ul className={styles.refs}>
      {refs.map((r) => (
        <li key={`${r.path}#${r.symbol}`}>
          <span>
            <RepoPath path={r.path} /> · <strong>{r.symbol}</strong>
          </span>
          <span className="muted small">{r.why}</span>
        </li>
      ))}
    </ul>
  );
}

export function Readings({ items }: { items: Reading[] }) {
  return (
    <ul>
      {items.map((r) => (
        <li key={r.cite}>
          {r.cite}. <em>{r.title}</em>. {r.venue}.
        </li>
      ))}
    </ul>
  );
}

export function Disclaimer() {
  return (
    <p className={styles.disclaimer}>
      Education and research only. Nothing here is investment advice or a recommendation about any security. Event-study numbers are
      historical averages from past data; backtest and simulator numbers are hypothetical and do not include every real-world cost. Past
      patterns may not repeat. See the <Link href="/legal/disclaimer">disclaimer</Link> and <Link href="/methodology">methodology</Link>.
    </p>
  );
}

/** Inline JSON-LD with "<" escaped so no string can close the script tag. */
export function JsonLd({ data }: { data: object }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }} />;
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const cls = verdict === "replicated" ? styles.vRep : verdict === "underpowered" ? styles.vUnder : styles.vNot;
  const icon = verdict === "replicated" ? "✓" : verdict === "underpowered" ? "○" : "✗";
  return (
    <span className={`${styles.verdict} ${cls}`}>
      <span aria-hidden="true">{icon}</span> {verdict}
    </span>
  );
}

export const fmtT = (t: number | null | undefined) => (typeof t === "number" && Number.isFinite(t) ? t.toFixed(2) : "—");
