// Factual, data-only text for ticker pages: the summary paragraph, meta description and JSON-LD date.
// Content rules (frontend/AGENTS.md): impersonal facts with dates; no advice, no judgement adjectives.
import type { Article, Fundamentals, Halt, TickerDetail } from "@/lib/api";
import { formatMoney } from "@/lib/format";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "2026-06-30" or an ISO timestamp -> "June 30, 2026" (UTC, deterministic on server and client). */
export function longDate(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

/** "Jun 30, 2026" */
export function shortDate(iso: string): string {
  const long = longDate(iso);
  return long.replace(/^([A-Z][a-z]{2})[a-z]*/, "$1");
}

const CAP_WORDS: Record<string, string> = { nano: "nano-cap", micro: "micro-cap", small: "small-cap", mid: "mid-cap", large: "large-cap" };

function pctText(v: number, digits?: number): string {
  const a = Math.abs(v) * 100;
  return `${a.toFixed(digits ?? (a < 10 ? 1 : 0))}%`;
}

/** Most recent article that carries a filing signal, and its highest-severity signal. */
export function latestSignal(articles: Article[]): { label: string; form: string | null; date: string } | null {
  const withSignals = articles
    .filter((a) => a.signals.length > 0)
    .sort((a, b) => b.published_at.localeCompare(a.published_at));
  const a = withSignals[0];
  if (!a) return null;
  const top = [...a.signals].sort((x, y) => y.severity - x.severity)[0];
  return { label: top.label, form: a.form, date: a.published_at };
}

function latestHalt(halts: Halt[]): string {
  return halts.reduce((m, h) => (h.halted_at > m ? h.halted_at : m), halts[0].halted_at);
}

export interface TickerData {
  detail: TickerDetail;
  fundamentals: Fundamentals | null;
  halts: Halt[] | null;
}

function displayName(d: TickerDetail): string {
  return d.name ?? d.symbol;
}

const DAY_MS = 86_400_000;

/**
 * Sentences for the visible summary paragraph. Each one is skipped when its data is missing.
 * Pages are cached (ISR), so every time window is written with explicit dates anchored at `asOf`
 * (the render time of the data), never as an undated "in the last N days".
 */
export function summarySentences({ detail: d, fundamentals: f, halts }: TickerData, days = 90, asOf: Date = new Date()): string[] {
  const out: string[] = [];
  const name = displayName(d);
  const to = longDate(asOf.toISOString());
  const yearAgo = longDate(new Date(asOf.getTime() - 365 * DAY_MS).toISOString());

  if (d.size_bucket && d.public_float != null) {
    const asOf = d.float_as_of ? ` as of ${longDate(d.float_as_of)}` : "";
    out.push(`${name} (${d.symbol}) is a ${CAP_WORDS[d.size_bucket] ?? d.size_bucket} company (public float ${formatMoney(d.public_float)}${asOf}).`);
  } else {
    out.push(`${name} (${d.symbol}) is a company whose SEC filings and news Afterfile tracks.`);
  }

  if (f?.cash) {
    const cash = `As of ${longDate(f.cash.as_of)} it reported ${formatMoney(f.cash.value)} in cash`;
    const r = f.runway;
    const ocfEnd = f.operating_cash_flow?.period_end;
    const period = ocfEnd ? `the 12 months to ${longDate(ocfEnd)}` : "its latest reported 12-month period";
    if (r.status === "burning" && r.months != null) {
      out.push(`${cash} and about ${r.months.toFixed(1)} months of runway at its operating cash burn for ${period} (arithmetic on reported figures, before any later raise).`);
    } else if (r.status === "cash_flow_positive") {
      out.push(`${cash}; its operating cash flow for ${period} was positive.`);
    } else {
      out.push(`${cash}.`);
    }
  }

  const sc = f?.share_change_1y;
  if (sc) {
    const verb = sc.change > 0.0005 ? `rose ${pctText(sc.change)}` : sc.change < -0.0005 ? `fell ${pctText(sc.change)}` : "was roughly unchanged";
    out.push(`Its reported shares outstanding ${verb} between ${longDate(sc.from)} and ${longDate(sc.to)}.`);
  }

  if (f) {
    const n = f.offerings_last_12m;
    out.push(`It filed ${n} priced offering prospectus${n === 1 ? "" : "es"} (424B) between ${yearAgo} and ${to}.`);
  }

  const si = f?.short_interest;
  if (si && si.pct_of_shares_outstanding != null) {
    out.push(`FINRA reported short interest of ${pctText(si.pct_of_shares_outstanding, 1)} of shares outstanding for the ${longDate(si.date)} settlement date.`);
  }

  const sig = latestSignal(d.articles);
  if (sig) {
    out.push(`The most recent filing signal was "${sig.label}"${sig.form ? ` (${sig.form})` : ""} on ${longDate(sig.date)}.`);
  }

  if (halts && halts.length > 0) {
    out.push(`Trading halts and pauses recorded between ${yearAgo} and ${to}: ${halts.length}, most recently on ${longDate(latestHalt(halts))}.`);
  }

  out.push(`Afterfile recorded ${d.mentions} mention${d.mentions === 1 ? "" : "s"} of ${d.symbol} in news and SEC filings in the ${days} days to ${to}.`);
  return out;
}

/** About 150 characters for <meta name="description">, most important facts first. */
export function metaDescription({ detail: d, fundamentals: f }: TickerData): string {
  const head = d.name ? `${d.symbol} (${d.name})` : d.symbol;
  const parts: string[] = [];
  if (d.size_bucket) parts.push(CAP_WORDS[d.size_bucket] ?? d.size_bucket);
  if (f?.runway.status === "burning" && f.runway.months != null && f.cash) {
    parts.push(`${f.runway.months.toFixed(1)} mo cash runway (${shortDate(f.cash.as_of)})`);
  } else if (f?.runway.status === "cash_flow_positive") {
    parts.push("cash-flow positive (TTM)");
  }
  if (f?.share_change_1y) {
    const c = f.share_change_1y.change;
    parts.push(`shares ${c >= 0 ? "+" : "-"}${pctText(c)} in 1y`);
  }
  if (f?.short_interest?.pct_of_shares_outstanding != null) {
    parts.push(`short interest ${pctText(f.short_interest.pct_of_shares_outstanding, 1)}`);
  }
  const sig = latestSignal(d.articles);
  if (sig) parts.push(`latest signal: ${sig.label}, ${shortDate(sig.date)}`);

  const fallback = `${head}: SEC filing signals, dilution history and cash runway from public SEC data.`;
  if (parts.length === 0) return fallback;

  let text = `${head}: ${parts.join(", ")}.`;
  // Drop facts from the end until it fits (keep at least the first one).
  while (text.length > 160 && parts.length > 1) {
    parts.pop();
    text = `${head}: ${parts.join(", ")}.`;
  }
  if (text.length < 110 && text.length + 30 <= 160) text += " SEC filings & dilution history.";
  return text;
}

/** Latest dated fact on the page, for JSON-LD dateModified. Null when nothing is dated. */
export function lastModified({ detail: d, fundamentals: f, halts }: TickerData): string | null {
  const dates: string[] = [];
  for (const a of d.articles) dates.push(a.published_at);
  if (halts && halts.length > 0) dates.push(latestHalt(halts));
  if (f?.dilution_filings[0]) dates.push(f.dilution_filings[0].filed);
  if (f?.cash) dates.push(f.cash.as_of);
  const times = dates.map((s) => new Date(s.length === 10 ? `${s}T00:00:00Z` : s).getTime()).filter((t) => !Number.isNaN(t));
  if (times.length === 0) return null;
  return new Date(Math.max(...times)).toISOString();
}
