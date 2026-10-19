import Link from "next/link";

import { pct, pctOr, SIZE_LABELS } from "@/lib/format";
import type { Lesson } from "@/lib/learn/lessons";
import { isoDay } from "@/lib/learn/live";
import { getEventStudy } from "@/lib/server-api";

import { HBarChart } from "../charts";
import styles from "../learn.module.css";
import LessonLayout from "../LessonLayout";
import { ApiNote, fmtT, LiveTag } from "../parts";

const BUCKETS = ["nano", "micro", "small", "mid", "large"];

export default async function BaselinesLesson({ lesson }: { lesson: Lesson }) {
  const main = await getEventStudy("main");
  const study = main.ok ? main.data : null;
  const base = study?.testing.baseline ?? {};
  const buckets = BUCKETS.filter((b) => typeof base[b]?.mean_20 === "number");
  const nanoRows = (study?.results ?? [])
    .filter((r) => r.bucket === "nano" && r.horizon_days === 20 && r.excess_vs_baseline !== null)
    .sort((a, b) => a.mean_abnormal - b.mean_abnormal)
    .slice(0, 8);
  const nanoBase = base.nano?.mean_20;

  return (
    <LessonLayout
      lesson={lesson}
      dataDate={isoDay(study?.generated_at)}
      meaning={
        <>
          <p>
            Every QuantDesk evidence line reports the drift <em>and</em> the excess over ordinary days, and a signal only counts as
            significant if its excess passes the same multiple-testing bar as its raw drift (<code>t_vs_baseline</code>).
          </p>
          {study && typeof nanoBase === "number" && (
            <p>
              <LiveTag kind="historical" date={study.generated_at} what="study generated" /> In the live study, nano caps drifted{" "}
              {pct(nanoBase)} vs the index over 20 ordinary trading days. Any nano-cap signal that merely matches that number tells you
              about nano caps, not about the filing.
            </p>
          )}
        </>
      }
    >
      <p className={styles.lede}>
        &quot;After this filing, the stock fell 4% vs the index&quot; sounds like information. It is not, if the same stocks fall 4% vs the index
        in any random month.
      </p>

      <section className={styles.section}>
        <h2>The problem: small caps have their own drift</h2>
        <p>
          Tiny companies often underperform the index for long stretches: they issue shares, burn cash and get delisted. So the right
          comparison for a nano-cap filing is not zero, it is <strong>the same companies on ordinary days</strong>.
        </p>
      </section>

      <section className={styles.section}>
        <h2>How QuantDesk builds the baseline</h2>
        <p>
          <code>baseline_events</code> creates pseudo-events for every sampled company at 10:00 ET every 21 trading days, roughly once a
          month, and measures them with exactly the same code as real filings. The <strong>excess</strong> is the event mean minus the
          baseline mean for that size bucket and horizon, and <code>welch_t</code> tests whether the difference is larger than noise
          (Welch&apos;s t allows the two groups to have different spreads).
        </p>
      </section>

      {study ? (
        <>
          <section className={styles.panel}>
            <h3>Ordinary-day drift by size, 20 trading days</h3>
            <HBarChart
              title="Ordinary-day 20-day drift vs the index, by size bucket"
              desc={buckets.map((b) => `${b} ${pct(base[b].mean_20)}`).join(", ")}
              format={(v) => pct(v, 2)}
              data={buckets.map((b) => ({ label: SIZE_LABELS[b] ?? b, value: base[b].mean_20 }))}
            />
            <p className="muted small">
              <LiveTag kind="historical" date={study.generated_at} what="study generated" /> Baseline observations per bucket:{" "}
              {buckets.map((b) => `${b} ${(base[b].n ?? 0).toLocaleString()}`).join(", ")}. Window {study.config.window[0]} to{" "}
              {study.config.window[1]}.
            </p>
          </section>

          {nanoRows.length > 0 && (
            <section className={styles.panel}>
              <h3>Nano-cap signals: raw drift vs excess over ordinary days (20 days)</h3>
              <div className={styles.tableScroll}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Signal</th>
                      <th>n</th>
                      <th>Drift vs index</th>
                      <th>Ordinary days</th>
                      <th>Excess</th>
                      <th>t (drift)</th>
                      <th>t vs ordinary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nanoRows.map((r) => (
                      <tr key={r.signal}>
                        <td>{r.label}</td>
                        <td>{r.n}</td>
                        <td>{pct(r.mean_abnormal)}</td>
                        <td>{pctOr(r.baseline_mean)}</td>
                        <td>{pctOr(r.excess_vs_baseline)}</td>
                        <td>{fmtT(r.t_stat)}</td>
                        <td>{fmtT(r.t_vs_baseline)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                <LiveTag kind="historical" date={study.generated_at} what="study generated" /> The most negative raw drifts first. Compare
                the two t columns: a large t on drift can shrink once the ordinary-day drift is subtracted.
              </p>
            </section>
          )}
        </>
      ) : (
        <ApiNote what="event study" status={main.ok ? 0 : main.status} />
      )}

      <section className={styles.section}>
        <h2>A caveat the code admits</h2>
        <p>
          Events and baseline share companies, so they are not independent samples. The plain Welch t ignores that; the clustered version
          (<code>clustered_welch_t</code>) is reported too and is described as approximate in the study&apos;s caveats. The{" "}
          <Link href="/learn/clustered-errors">clustered errors lesson</Link> covers why this matters.
        </p>
      </section>
    </LessonLayout>
  );
}
