// Pure helpers for the landing page's "Key findings" cards. No React, no fetch: app/page.tsx fetches the three
// studies through server-api.ts (getEventStudy) and passes each Result in. Every card degrades to a fallback
// sentence when its study is missing (404), the API is down (status 0) or the expected row is absent.

import type { EventStudy } from "@/lib/api";
import { dateLabel, findRow } from "@/lib/learn/live";
import type { Result } from "@/lib/server-api";

export interface Finding {
  key: string;
  kicker: string;
  /** Headline number or verdict, or null when the study could not be read. */
  value: string | null;
  /** One factual sentence explaining the value (or why it is missing). */
  text: string;
  /** "Historical" or "Hypothetical" labels shown on the card. */
  labels: string[];
  date: string | null;
  href: string;
  linkLabel: string;
}

/** Signed percent with two decimals: 0.0866 -> "+8.66%". */
export function pct(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  const v = (x * 100).toFixed(2);
  return `${x > 0 ? "+" : ""}${v}%`;
}

function missing(result: Result<EventStudy>, what: string): string {
  if (result.ok) return `The ${what} result is not in the current study file.`;
  if (result.status === 404) return `The ${what} study has not been run on this machine yet.`;
  return `The API is not reachable right now, so the ${what} result cannot be shown. Start the backend and reload.`;
}

export function offeringFinding(main: Result<EventStudy>): Finding {
  const base = {
    key: "in-sample",
    kicker: "In-sample event study",
    href: "/lab",
    linkLabel: "See the Edge Lab",
  };
  const row = main.ok ? findRow(main.data, "offering_priced", "nano", 20) : undefined;
  if (!main.ok || !row) {
    return { ...base, value: null, text: missing(main, "in-sample offering"), labels: ["Historical"], date: null };
  }
  return {
    ...base,
    value: pct(row.mean_abnormal),
    text:
      `Nano-cap companies that priced an offering drifted ${pct(row.mean_abnormal)} against the benchmark over the next 20 trading days ` +
      `(n = ${row.n}, t = ${row.t_stat.toFixed(2)}); ${pct(row.mean_net)} per event after assumed costs and borrow.`,
    labels: ["Historical", "Net figure hypothetical"],
    date: main.data.generated_at,
  };
}

export function oosFinding(oos: Result<EventStudy>): Finding {
  const base = {
    key: "oos",
    kicker: "Pre-registered replication",
    href: "/lab?study=oos",
    linkLabel: "See the verdicts",
  };
  const h1 = oos.ok ? oos.data.confirmatory?.find((c) => c.signal === "offering_priced") ?? oos.data.confirmatory?.[0] : undefined;
  if (!oos.ok || !h1) {
    return { ...base, value: null, text: missing(oos, "out-of-sample replication"), labels: ["Historical"], date: null };
  }
  const all = oos.data.confirmatory ?? [];
  const replicated = all.filter((c) => c.verdict === "replicated").length;
  const tc = h1.t_clustered === null ? "n/a" : h1.t_clustered.toFixed(2);
  return {
    ...base,
    value: h1.verdict === "replicated" ? "Replicated" : h1.verdict === "underpowered" ? "Underpowered" : "Not replicated",
    text:
      `On earlier years and new companies, the ${h1.buckets.join("/")}-cap ${h1.label.charAt(0).toLowerCase()}${h1.label.slice(1)} drift was ${pct(h1.mean_abnormal)} (clustered t = ${tc}), ` +
      `but ${pct(h1.mean_net)} after costs and borrow. ${replicated} of ${all.length} pre-registered hypotheses replicated.`,
    labels: ["Historical", "Net figure hypothetical"],
    date: oos.data.generated_at,
  };
}

export function insiderFinding(insider: Result<EventStudy>): Finding {
  const base = {
    key: "insider",
    kicker: "Form 4 insider purchases",
    href: "/lab?study=insider_purchases",
    linkLabel: "See the insider study",
  };
  const row = insider.ok ? findRow(insider.data, "insider_cluster_purchase", "micro", 5) : undefined;
  if (!insider.ok || !row) {
    return { ...base, value: null, text: missing(insider, "insider cluster purchase"), labels: ["Historical"], date: null };
  }
  const tc = row.t_stat_clustered ?? row.t_stat;
  const companies = row.companies ? `, ${row.companies} firms` : "";
  return {
    ...base,
    value: pct(row.excess_vs_baseline ?? row.mean_abnormal),
    text:
      `Micro-cap cluster purchases by directors and officers were followed by ${pct(row.excess_vs_baseline ?? row.mean_abnormal)} ` +
      `excess drift over ordinary days within 5 trading days (n = ${row.n}${companies}, clustered t = ${tc.toFixed(2)}); ` +
      `${pct(row.mean_net)} per event after assumed costs.`,
    labels: ["Historical", "Net figure hypothetical"],
    date: insider.data.generated_at,
  };
}

export function studyDate(f: Finding): string | null {
  return f.date ? dateLabel(f.date) : null;
}
