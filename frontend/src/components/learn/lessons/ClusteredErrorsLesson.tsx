import { pct } from "@/lib/format";
import type { Lesson } from "@/lib/learn/lessons";
import { findRow, isoDay } from "@/lib/learn/live";
import { getEventStudy } from "@/lib/server-api";

import ClusterSimulator from "../ClusterSimulator";
import ConfirmatoryBlock from "../ConfirmatoryBlock";
import styles from "../learn.module.css";
import LessonLayout from "../LessonLayout";
import { ApiNote, fmtT, LiveTag, RepoPath, Stat } from "../parts";

export default async function ClusteredErrorsLesson({ lesson }: { lesson: Lesson }) {
  const [main, oos] = await Promise.all([getEventStudy("main"), getEventStudy("oos")]);
  const study = main.ok ? main.data : null;
  const oosStudy = oos.ok ? oos.data : null;
  const row = findRow(study, "offering_priced", "nano", 20);
  const dates = [study?.generated_at, oosStudy?.generated_at].map(isoDay).filter((d): d is string => !!d).sort();

  return (
    <LessonLayout
      lesson={lesson}
      dataDate={dates[dates.length - 1] ?? null}
      meaning={
        <>
          <p>
            In the main study the clustered t-stats are reported next to the plain ones but do not decide significance (the rule was fixed
            before they were added, and changing it afterwards would be a new design). The pre-registered out-of-sample test and the
            insider-purchase study use the clustered t as the deciding statistic from the start.
          </p>
          {row && row.t_stat_clustered != null && (
            <p>
              <LiveTag kind="historical" date={study!.generated_at} what="study generated" /> For priced offerings at nano caps over 20
              days, clustering by company moves the t-stat from {fmtT(row.t_stat)} to {fmtT(row.t_stat_clustered)} ({row.n} events,{" "}
              {row.clusters ?? row.companies} companies).
            </p>
          )}
        </>
      }
    >
      <p className={styles.lede}>
        A t-stat assumes each observation is fresh, independent evidence. Five offerings by the same struggling company are closer to one
        piece of evidence repeated five times.
      </p>

      <section className={styles.section}>
        <h2>Why events cluster</h2>
        <p>
          Small companies that raise money once tend to do it again: shelf takedowns, at-the-market programs, follow-ons. Their filings
          share the same balance sheet, the same investors and often the same downward trend. If one company&apos;s stock collapses, all of
          its events look like strong evidence at once. The naive standard error, sd / √n, counts n events; the effective sample size is
          closer to the number of companies.
        </p>
      </section>

      <section className={styles.section}>
        <h2>The CR1 cluster-robust standard error</h2>
        <p>
          <code>clustered_se</code> sums the deviations from the mean <em>within</em> each company first, squares those company totals,
          and scales by G/(G − 1) for G companies:
        </p>
        <p className={styles.code}>se = sqrt( G/(G−1) × Σ_g ( Σ_(i in g) (x_i − mean) )² ) / n</p>
        <p>
          If every company has one event this equals the ordinary sd / √n. If a company&apos;s events move together, their deviations add up
          before squaring and the standard error grows. Petersen (2009) showed that ignoring this kind of correlation is one of the most
          common ways finance studies overstate significance.
        </p>
      </section>

      <ClusterSimulator />

      {study ? (
        row ? (
          <section className={styles.panel}>
            <h3>The real case: priced offerings at nano caps, 20 days</h3>
            <div className={styles.stats}>
              <Stat label="Events" value={row.n} sub={`${row.clusters ?? row.companies} companies`} />
              <Stat label="Mean drift vs index" value={pct(row.mean_abnormal)} />
              <Stat label="Plain t" value={fmtT(row.t_stat)} />
              <Stat label="Clustered t" value={row.t_stat_clustered != null ? fmtT(row.t_stat_clustered) : "not in this file"} sub={`bar: |t| ≥ ${study.testing.t_critical}`} />
            </div>
            <p className="muted small">
              <LiveTag kind="historical" date={study.generated_at} what="study generated" />{" "}
              {row.t_stat_clustered == null
                ? "This study file was generated before clustered t-stats were added; the next run of the Edge Lab includes them."
                : "Same events, same mean: only the standard error changes."}
            </p>
          </section>
        ) : null
      ) : (
        <ApiNote what="event study" status={main.ok ? 0 : main.status} />
      )}

      <section className={styles.section}>
        <h2>Out of sample: the confirmatory test</h2>
        <p>
          The in-sample leads were re-tested on 2020 to 2023 filings by companies the original study never sampled, under rules written down
          in <RepoPath path="backend/app/research/PREREGISTRATION_OOS.md" /> before the run. Each hypothesis needs a clustered |t| above the
          Bonferroni bar for a family of three, enough events and companies, the registered direction, and a positive result after costs.
          Otherwise it is &quot;not replicated&quot;, or &quot;underpowered&quot; when the sample is too small to tell.
        </p>
        {oosStudy?.confirmatory?.length ? (
          <ConfirmatoryBlock study={oosStudy} heading="h3" />
        ) : (
          <p className={styles.note}>
            {oos.ok || oos.status === 404
              ? "The out-of-sample study has not been run yet. Its verdicts will appear here (and on the Edge Lab page) once it has."
              : "The out-of-sample results could not be loaded right now (API unavailable)."}
          </p>
        )}
      </section>
    </LessonLayout>
  );
}
