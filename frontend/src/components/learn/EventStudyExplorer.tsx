"use client";

import { useMemo, useState } from "react";

import type { StudyResult } from "@/lib/api";
import { directionMark, pct, pctAbs, SIZE_LABELS } from "@/lib/format";

import { HBarChart } from "./charts";
import styles from "./learn.module.css";
import { fmtT, LiveTag, Stat } from "./parts";

const BUCKETS = ["nano", "micro", "small", "mid", "large"];

/** Pick a signal, size bucket and horizon from the live study and see how mean, baseline, excess and net relate. */
export default function EventStudyExplorer({
  rows,
  generatedAt,
  tCritical,
  window,
}: {
  rows: StudyResult[];
  generatedAt: string;
  tCritical: number;
  window: [string, string];
}) {
  const signals = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of rows) m.set(r.signal, r.label);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);
  const initial = rows.find((r) => r.signal === "offering_priced" && r.bucket === "nano" && r.horizon_days === 20) ?? rows[0];
  const [signal, setSignal] = useState(initial?.signal ?? "");
  const [bucket, setBucket] = useState<string>(initial?.bucket ?? "");
  const [horizon, setHorizon] = useState(initial?.horizon_days ?? 20);

  const bucketsFor = BUCKETS.filter((b) => rows.some((r) => r.signal === signal && r.bucket === b));
  const horizonsFor = [...new Set(rows.filter((r) => r.signal === signal && r.bucket === bucket).map((r) => r.horizon_days))].sort((a, b) => a - b);
  const row = rows.find((r) => r.signal === signal && r.bucket === bucket && r.horizon_days === horizon);

  const chooseSignal = (s: string) => {
    setSignal(s);
    const bs = BUCKETS.filter((b) => rows.some((r) => r.signal === s && r.bucket === b));
    if (!bs.includes(bucket)) setBucket(bs[0] ?? "");
  };

  if (!rows.length) return null;
  const sign = row?.direction === "-" ? -1 : 1;
  const gross = row ? sign * row.mean_abnormal : 0;

  return (
    <section className={styles.panel} aria-label="Event study explorer">
      <h3>Explore the live study</h3>
      <div className={styles.controls}>
        <label>
          Signal
          <select value={signal} onChange={(e) => chooseSignal(e.target.value)} style={{ width: 240 }}>
            {signals.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Size
          <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
            {bucketsFor.map((b) => (
              <option key={b} value={b}>
                {SIZE_LABELS[b] ?? b}
              </option>
            ))}
          </select>
        </label>
        <div className="seg" role="group" aria-label="Horizon">
          {horizonsFor.map((h) => (
            <button key={h} type="button" className={h === horizon ? "on" : ""} onClick={() => setHorizon(h)} aria-pressed={h === horizon}>
              {h}d
            </button>
          ))}
        </div>
      </div>
      {!row ? (
        <p className="muted small">No result for this combination (fewer than 20 events, so it was not tested).</p>
      ) : (
        <>
          <div className={styles.stats}>
            <Stat label="Mean drift vs index" value={pct(row.mean_abnormal, 2)} sub={`median ${pct(row.median_abnormal, 2)}`} />
            <Stat label="Same stocks, ordinary days" value={row.baseline_mean === null ? "—" : pct(row.baseline_mean, 2)} sub="baseline" />
            <Stat label="Excess vs ordinary days" value={row.excess_vs_baseline === null ? "—" : pct(row.excess_vs_baseline, 2)} sub={`t = ${fmtT(row.t_vs_baseline)}`} />
            <Stat label="Net after costs" value={pct(row.mean_net, 2)} sub={`${pctAbs(row.cost)} costs${row.borrow > 0 ? ` incl. ${pctAbs(row.borrow)} borrow` : ""}`} />
            <Stat label="t-stat" value={fmtT(row.t_stat)} sub={row.t_stat_clustered != null ? `clustered ${fmtT(row.t_stat_clustered)}` : `bar: |t| ≥ ${tCritical.toFixed(2)}`} />
            <Stat label="Events" value={row.n} sub={`${row.companies} companies`} />
          </div>
          <HBarChart
            title={`${row.label}, ${row.bucket}, ${row.horizon_days} days`}
            desc="From the measured drift to the net result after costs."
            format={(v) => pct(v, 2)}
            data={[
              { label: "Day-0 reaction (not tradable)", value: row.mean_reaction, tone: "muted" },
              { label: "Mean drift vs index", value: row.mean_abnormal },
              ...(row.baseline_mean !== null ? [{ label: "Ordinary-day drift", value: row.baseline_mean, tone: "muted" as const }] : []),
              ...(row.excess_vs_baseline !== null ? [{ label: "Excess vs ordinary days", value: row.excess_vs_baseline }] : []),
              { label: `Gross, ${row.direction === "-" ? "for a decline (▼)" : "for a rise (▲/◆)"}`, value: gross },
              { label: "Costs and borrow", value: -row.cost, tone: "flag" },
              { label: "Net after costs", value: row.mean_net },
            ]}
          />
          <p className="small">
            {directionMark(row.direction)} The direction was fixed before the study ran ({row.direction === "-" ? "a decline was expected, so the gross result is the drift with its sign flipped" : "a rise, or no prior, so the gross result is the drift as measured"}).
            Net = gross − {pctAbs(row.cost, 2)}. Verdict under Afterfile&apos;s rule:{" "}
            <strong>{row.significant ? "survives the multiple-testing correction, the baseline test and costs" : row.nominal_significant ? "nominal only (|t| ≥ 1.96 but fails the full rule)" : "not significant"}</strong>.
          </p>
        </>
      )}
      <p className="muted small">
        <LiveTag kind="historical" date={generatedAt} what="study generated" /> Market-adjusted averages for filings from {window[0]} to{" "}
        {window[1]}; net figures are hypothetical (assumed costs, close fills). Past averages, not forecasts.
      </p>
    </section>
  );
}
