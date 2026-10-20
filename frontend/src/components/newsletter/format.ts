// Plain helpers shared by server components (issue pages, metadata, sitemap) and the client archive.
// Kept out of the "use client" modules: a server component importing a non-component export from a
// client module gets a client reference, not the function.
// RULE: never add "use client" (or React/browser-only imports) here. app/newsletter pages,
// generateMetadata and app/sitemap.ts import it on the server.

import type { NewsletterHeadline } from "@/lib/api";

/** Issue ids are ISO weeks, e.g. 2026-W41 (same pattern the backend validates). */
const ISSUE_ID_RE = /^\d{4}-W\d{2}$/;

/** Route param -> issue id, or null when it cannot be one (caller 404s without an API call). */
export function parseIssueId(raw: string): string | null {
  const s = raw.trim().toUpperCase();
  return ISSUE_ID_RE.test(s) ? s : null;
}

export const issuePath = (id: string) => `/newsletter/${encodeURIComponent(id)}`;

/** Filing / halt time in Eastern time, like the email version. */
export function etTime(iso: string): string {
  return (
    new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) +
    " ET"
  );
}

/** Calendar day of an ISO date or timestamp (its date part), timezone-independent. */
export function dayLabel(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}

export function weekLabel(issue: { week_start: string; week_end: string }): string {
  const md = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  return `${md(issue.week_start)} to ${md(issue.week_end)}, ${issue.week_end.slice(0, 4)}`;
}

/** <title> of an issue page. */
export function issueTitle(issue: { week_start: string; week_end: string }): string {
  return `Small-Cap Filing Radar: ${weekLabel(issue)} | Undertow`;
}

const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;

/** Factual meta description from the headline counts (impersonal, no buy/sell language). */
export function issueDescription(issue: {
  week_start: string;
  week_end: string;
  headline: NewsletterHeadline;
  coverage_note?: string | null;
}): string {
  const h = issue.headline;
  let text =
    `Weekly Small-Cap Filing Radar for ${weekLabel(issue)}: ` +
    `${plural(h.signal_filings, "SEC signal filing", "SEC signal filings")} from ${plural(h.companies, "company", "companies")} under $2B public float ` +
    `(${h.by_severity["3"]} high severity, ${h.by_severity["2"]} medium), ` +
    `${plural(h.dilution_watch, "company", "companies")} on dilution watch and ${plural(h.serious_halts, "serious trading halt", "serious trading halts")}.`;
  if (issue.coverage_note) text += ` ${issue.coverage_note}`;
  return text;
}
