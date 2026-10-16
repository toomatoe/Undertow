"use client";

import type { JournalStatus } from "@/lib/api";
import { DIRECTION_WORDS, directionMark, pct, SIZE_LABELS } from "@/lib/format";

import { Signed } from "../backtest/parts";

export const STATUS_INFO: Record<JournalStatus, { icon: string; short: string; long: string }> = {
  waiting: { icon: "○", short: "Waiting", long: "Waiting for entry price" },
  open: { icon: "◐", short: "Open", long: "Open: entry priced, results filling in" },
  complete: { icon: "✓", short: "Complete", long: "Complete: 20-day result in" },
  data_ended: { icon: "✗", short: "Data ended", long: "Price data stopped (delisted or halted)" },
  no_data: { icon: "✗", short: "No data", long: "No price data for this ticker" },
};

export const STATUS_ORDER: JournalStatus[] = ["waiting", "open", "complete", "data_ended", "no_data"];

export function StatusBadge({ status }: { status: JournalStatus }) {
  const s = STATUS_INFO[status] ?? { icon: "?", short: status, long: status };
  return (
    <span className={`tr-status tr-status-${status}`} title={s.long}>
      <span aria-hidden="true">{s.icon}</span> {s.short}
    </span>
  );
}

/** Expected direction of a signal: ▼ / ▲ / ◆ with a text alternative. */
export function DirMark({ d }: { d: string }) {
  const word = DIRECTION_WORDS[d] ?? "direction unclear";
  return (
    <span className={`tr-dir tr-dir-${d === "-" ? "neg" : d === "+" ? "pos" : "unk"}`} title={word} aria-label={word} role="img">
      {directionMark(d)}
    </span>
  );
}

export const sizeShort = (b: string | null) => (b ? b[0].toUpperCase() + b.slice(1) : "—");
export const sizeTitle = (b: string | null) => (b ? SIZE_LABELS[b] ?? b : "Unknown size");

/** Abnormal return (stock minus IWM) with ▲/▼ so sign never depends on color. */
export function Abn({ v }: { v: number | null | undefined }) {
  return <Signed v={v} fmt={(x) => pct(x)} />;
}

export function formatFiled(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export function formatDay(iso: string | null): string {
  if (!iso) return "—";
  return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : Array.isArray(v) ? v.join(" ") : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function downloadCsv(header: string[], rows: unknown[][], name: string) {
  const text = [header.join(","), ...rows.map((r) => r.map(csvCell).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
