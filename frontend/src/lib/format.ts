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
  { value: "", label: "All sizes" },
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

export function humanize(code: string): string {
  return code.replace(/_/g, " ");
}

export const SOURCE_LABELS: Record<string, string> = {
  rss: "News",
  edgar: "SEC filing",
  alpaca: "Benzinga",
};
