import Link from "next/link";

import { pct } from "@/lib/format";
import type { Lesson } from "@/lib/learn/lessons";
import { findRow, isoDay } from "@/lib/learn/live";
import { getEventStudy } from "@/lib/server-api";

import EventStudyExplorer from "../EventStudyExplorer";
import styles from "../learn.module.css";
import LessonLayout from "../LessonLayout";
import { ApiNote, fmtT, LiveTag, Stat } from "../parts";

export default async function EventStudyLesson({ lesson }: { lesson: Lesson }) {
  const main = await getEventStudy("main");
  const study = main.ok ? main.data : null;
  const lead = findRow(study, "offering_priced", "nano", 20);
  const survivors = study?.results.filter((r) => r.significant) ?? [];

  return (
    <LessonLayout
      lesson={lesson}
      dataDate={isoDay(study?.generated_at)}
      meaning={
        study ? (
          <>
            <p>
              <LiveTag kind="historical" date={study.generated_at} what="study generated" /> Afterfile&apos;s Edge Lab ran{" "}
              {study.testing.n_tests} tests on {study.measured_events.toLocaleString()} filing events from {study.config.window[0]} to{" "}
              {study.config.window[1]}. {survivors.length} {survivors.length === 1 ? "cell" : "cells"} passed every rule (multiple-testing
              correction, the ordinary-day baseline, the expected direction and costs).
            </p>
            {lead && (
              <p>
                The strongest lead: <strong>{lead.label}</strong> at nano caps over 20 trading days averaged {pct(lead.mean_abnormal)} vs the
                index (n = {lead.n} events, {lead.companies} companies, t = {fmtT(lead.t_stat)}), {pct(lead.mean_net)} after assumed costs
                and borrow (hypothetical). An average past drift is not a tradable result: the{" "}
                <Link href="/learn/sharpe-dsr-backtest-pitfalls">backtest lesson</Link> shows what happens once real-world frictions are
                added.
              </p>
            )}
          </>
        ) : (
          <p>
            Every signal card on Afterfile carries an evidence line from this kind of study. When the live study loads, this section shows
            how many of its tests survived and the strongest lead.
          </p>
        )
      }
    >
      <p className={styles.lede}>
        An event study asks a narrow question: after a specific kind of event, what did similar stocks do next, compared with the market?
        Afterfile uses it to attach historical context to every SEC filing signal.
      </p>

      <section className={styles.section}>
        <h2>1. Abnormal return: compared with what the market did</h2>
        <p>
          A stock that rose 3% on a day the small-cap index rose 3% did nothing unusual. The <strong>abnormal return</strong> is the
          stock&apos;s return minus its benchmark&apos;s return over exactly the same dates: IWM (Russell 2000) for small companies, SPY for
          large ones. <code>bench_ret</code> refuses to compute it unless both series have a price on both dates, so a missing day never
          silently shifts the window.
        </p>
      </section>

      <section className={styles.section}>
        <h2>2. Day 0: the first close anyone could act on</h2>
        <p>
          EDGAR stamps each filing with an acceptance time. <code>day0_index</code> converts it to US Eastern time: a filing accepted before
          15:30 ET uses that day&apos;s close as day 0; at or after 15:30 ET, the next trading day&apos;s close. The 30-minute margin is there
          because nobody reads, classifies and acts on a filing in the last seconds before the bell. If there is no bar within five days
          (a halt, a data gap) the event is dropped rather than guessed.
        </p>
      </section>

      <section className={styles.section}>
        <h2>3. Reaction vs drift</h2>
        <p>
          <strong>Reaction</strong> is day-0 close vs the previous close: the move that happened as the news came out, mostly before anyone
          could respond. <strong>Drift</strong> runs from the day-0 close to the close 5 or 20 trading days later: the part that, in
          principle, someone could have captured. Afterfile reports both but judges a signal on drift. A big reaction with no drift is a
          market that priced the news immediately.
        </p>
      </section>

      <section className={styles.section}>
        <h2>4. From average drift to a net number</h2>
        <p>
          Each signal has a direction fixed before any data was seen (▼ expected decline, ▲ rise, ◆ unclear). <code>summarize</code>{" "}
          averages the winsorized drifts per signal, size bucket and horizon, flips the sign for ▼ signals, and subtracts a round-trip cost
          per size bucket plus a borrow fee for ▼ signals. That is <code>mean_net</code>: a hypothetical figure, because real fills in
          illiquid stocks are usually worse than the close.
        </p>
      </section>

      {study ? (
        <>
          <div className={styles.stats}>
            <Stat label="Filing events measured" value={study.measured_events.toLocaleString()} sub={<LiveTag kind="historical" date={study.generated_at} />} />
            <Stat label="Tests run" value={study.testing.n_tests} sub={`signal × size × horizon`} />
            <Stat label="Survive every rule" value={survivors.length} sub={`|t| ≥ ${study.testing.t_critical}`} />
          </div>
          <EventStudyExplorer rows={study.results} generatedAt={study.generated_at} tCritical={study.testing.t_critical} window={study.config.window} />
        </>
      ) : (
        <ApiNote what="event study" status={main.ok ? 0 : main.status} />
      )}
    </LessonLayout>
  );
}
