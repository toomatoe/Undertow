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

export const SOURCE_LABELS: Record<string, string> = {
  rss: "News",
  edgar: "SEC filing",
  alpaca: "Benzinga",
};
