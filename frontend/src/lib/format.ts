export function timeAgo(iso: string): string {
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export function sentimentClass(score: number | null | undefined): string {
  if (score === null || score === undefined) return "sent-none";
  if (score > 0.15) return "sent-pos";
  if (score < -0.15) return "sent-neg";
  return "sent-neu";
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return "—";
  return (score > 0 ? "+" : "") + score.toFixed(2);
}

export const SIZE_LABELS: Record<string, string> = {
  nano: "Nano (<$50M)",
  micro: "Micro ($50–300M)",
  small: "Small ($300M–2B)",
  mid: "Mid ($2–10B)",
  large: "Large (>$10B)",
};

export const SIZE_FILTERS = [
  { value: "all", label: "All sizes" },
  { value: "nano,micro,small", label: "Small caps (<$2B)" },
  { value: "nano,micro", label: "Micro & nano (<$300M)" },
  { value: "small", label: "Small ($300M–2B)" },
  { value: "mid,large", label: "Mid & large (>$2B)" },
];

export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${(v / 1e3).toFixed(0)}K`;
}

export function pct(v: number, digits = 1): string {
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

export function pctAbs(v: number, digits = 1): string {
  return `${(Math.abs(v) * 100).toFixed(digits)}%`;
}

export function humanize(code: string): string {
  return code.replace(/_/g, " ");
}

export const SOURCE_LABELS: Record<string, string> = {
  rss: "News",
  edgar: "SEC filing",
  alpaca: "Benzinga",
};

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Whole dollars with thousands separators: "$112,340", "-$4,210"; `signed` adds "+" to gains. */
export function formatUsd(v: number | null | undefined, signed = false): string {
  if (!finite(v)) return "—";
  const s = `$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (v < 0 && Math.round(Math.abs(v)) > 0) return `-${s}`;
  return signed && v > 0 ? `+${s}` : s;
}

/** Plain number with fixed decimals, or "—" when missing. */
export function fmtNum(v: number | null | undefined, digits = 2): string {
  return finite(v) ? v.toFixed(digits) : "—";
}

/** `pct` (signed) or `pctAbs` that tolerates missing values. */
export function pctOr(v: number | null | undefined, digits = 1, signed = true): string {
  if (!finite(v)) return "—";
  return signed ? pct(v, digits) : pctAbs(v, digits);
}

/** IBKR borrow fee (annual fraction) as "% / yr": "0.3% / yr", "49.7% / yr", "393% / yr". */
export function formatBorrowFee(v: number | null | undefined): string {
  if (!finite(v)) return "—";
  const p = v * 100;
  return `${p >= 100 ? p.toFixed(0) : p.toFixed(1)}% / yr`;
}

/** Expected direction of a signal as a shape (never color alone): ▼ down, ▲ up, ◆ either way. */
export function directionMark(d: string): string {
  return d === "-" ? "▼" : d === "+" ? "▲" : "◆";
}

export const DIRECTION_WORDS: Record<string, string> = {
  "-": "expected to fall",
  "+": "expected to rise",
  "?": "direction unclear",
};

/** A price with sensible decimals for penny stocks. */
export function formatPrice(v: number | null | undefined): string {
  if (!finite(v)) return "—";
  return `$${v < 1 ? v.toFixed(3) : v.toFixed(2)}`;
}
