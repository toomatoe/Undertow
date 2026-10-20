import Link from "next/link";

import type { Lesson } from "@/lib/learn/lessons";
import { isoDay } from "@/lib/learn/live";
import { bonferroniT } from "@/lib/learn/stats";
import { getBacktestReport, getEventStudy } from "@/lib/server-api";

import styles from "../learn.module.css";
import LessonLayout from "../LessonLayout";
import NoiseSimulator from "../NoiseSimulator";
import { ApiNote, LiveTag, Stat } from "../parts";

export default async function MultipleTestingLesson({ lesson }: { lesson: Lesson }) {
  const [main, report] = await Promise.all([getEventStudy("main"), getBacktestReport()]);
  const study = main.ok ? main.data : null;
  const nominal = study?.results.filter((r) => r.nominal_significant).length ?? 0;
  const significant = study?.results.filter((r) => r.significant).length ?? 0;
  const nTests = study?.testing.n_tests ?? 102;
  const trials = report.ok ? Number(report.data.overfitting?.trials ?? 0) : null;

  return (
    <LessonLayout
      lesson={lesson}
      dataDate={isoDay(study?.generated_at)}
      meaning={
        <>
          <p>
            Afterfile applies the correction to the whole grid it tested, not just to the rows that looked interesting, and the rule was
            written before the results existed (<code>backend/app/research/AGENTS.md</code>: change the design before looking at results,
            never after). A row that clears 1.96 but not the corrected bar is labelled &quot;nominal only&quot;: a lead for a new,
            pre-registered test, not a finding.
          </p>
          <p>
            The out-of-sample replication goes one step further: it tests only three hypotheses chosen in advance, so its bar is a
            Bonferroni family of 3 (|t| ≥ {bonferroniT(3).toFixed(3)}) rather than the whole grid. Fewer, pre-committed questions earn a lower
            bar honestly.
          </p>
          {trials !== null && report.ok && (
            <p>
              <LiveTag kind="hypothetical" date={report.data.generated_at} what="backtest report" /> The backtester counts every distinct
              configuration it has ever tried ({trials} so far) and deflates its Sharpe ratio for them: the same idea applied to strategies
              (see the <Link href="/learn/sharpe-dsr-backtest-pitfalls">deflated Sharpe lesson</Link>).
            </p>
          )}
        </>
      }
    >
      <p className={styles.lede}>
        A t-stat of 1.96 means a 5% chance of seeing an effect that large in pure noise. Run 100 tests and expect about five
        such &quot;discoveries&quot; even if nothing is real.
      </p>

      <section className={styles.section}>
        <h2>Why one threshold is not enough</h2>
        <p>
          The 5% error rate applies to one test. Afterfile&apos;s Edge Lab tests every signal × size bucket × horizon with at least 20
          events. If each test has a 5% false-positive rate, the chance that at least one of N independent tests fires by luck is 1 −
          0.95<sup>N</sup>: 64% for 20 tests, over 99% for 100.
        </p>
        <p>
          <strong>Bonferroni</strong> fixes the family-wise error rate by splitting the 5% across all N tests: each test must pass at 0.05 /
          N. For a two-sided normal test the cutoff is |t| ≥ Φ<sup>−1</sup>(1 − 0.05 / (2N)). It is conservative (it assumes the worst
          case about how tests overlap), which is the point when the goal is to avoid fooling yourself. Harvey, Liu &amp; Zhu (2016) argue
          for a similar bar across the whole finance literature: a new factor should clear a t-stat of about 3, not 2.
        </p>
      </section>

      {study ? (
        <div className={styles.stats}>
          <Stat label="Tests in the live study" value={study.testing.n_tests} sub={<LiveTag kind="historical" date={study.generated_at} />} />
          <Stat label="Bonferroni cutoff" value={`|t| ≥ ${study.testing.t_critical}`} sub={`= Φ⁻¹(1 − 0.05 / ${2 * study.testing.n_tests})`} />
          <Stat label="Pass |t| ≥ 1.96" value={nominal} sub={`about ${(0.05 * study.testing.n_tests).toFixed(0)} expected from noise alone`} />
          <Stat label="Pass the full rule" value={significant} sub="corrected t, baseline, direction, costs" />
        </div>
      ) : (
        <ApiNote what="event study" status={main.ok ? 0 : main.status} />
      )}

      <NoiseSimulator defaultSignals={nTests} />

      <section className={styles.section}>
        <h2>What the simulator shows</h2>
        <p>
          With {nTests} pure-noise signals, the 1.96 line typically flags a handful; the Bonferroni line (|t| ≥{" "}
          {bonferroniT(nTests).toFixed(2)}) almost never flags any. Fat tails make it slightly worse, because extreme events in a small
          sample produce extreme t-stats more often than the normal curve predicts. That is one reason Afterfile also winsorizes returns at
          the 1st and 99th percentile before testing.
        </p>
        <p>
          The correction only protects you if the count is honest. Trying ten versions of a signal and reporting the best one is ten
          tests, even if only one appears in the table. That is why Afterfile pre-registers designs and logs every backtest
          configuration.
        </p>
      </section>
    </LessonLayout>
  );
}
