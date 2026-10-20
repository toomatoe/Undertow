import { SIZE_LABELS } from "@/lib/format";
import type { Lesson } from "@/lib/learn/lessons";
import { isoDay } from "@/lib/learn/live";
import { getBacktestReport, getEventStudy } from "@/lib/server-api";

import styles from "../learn.module.css";
import LessonLayout from "../LessonLayout";
import { ApiNote, LiveTag } from "../parts";
import SurvivorshipSimulator from "../SurvivorshipSimulator";

const BUCKETS = ["nano", "micro", "small", "mid", "large"];
const share = (part: number, whole: number) => `${Math.round((100 * part) / Math.max(whole, 1))}%`;

export default async function SurvivorshipLesson({ lesson }: { lesson: Lesson }) {
  const [main, report] = await Promise.all([getEventStudy("main"), getBacktestReport()]);
  const study = main.ok ? main.data : null;
  const bt = report.ok ? report.data : null;
  const dates = [study?.generated_at, bt?.generated_at].map(isoDay).filter((d): d is string => !!d).sort();
  const nano = study?.coverage.nano;

  return (
    <LessonLayout
      lesson={lesson}
      dataDate={dates[dates.length - 1] ?? null}
      meaning={
        <>
          <p>
            Afterfile cannot recover the missing names from free data, so it does the next best thing: it counts them, publishes the count
            next to every result, and writes the direction of the bias into the study&apos;s caveats. The backtest goes further and never
            books a delisting as a gain (<code>delist_penalty</code>): a position in a stock whose data ends is closed at the last price
            plus 10%.
          </p>
          {study && nano && (
            <p>
              <LiveTag kind="historical" date={study.generated_at} what="study generated" /> Of the nano caps sampled for the live study,{" "}
              {nano.no_ticker ?? 0} of {(nano.companies ?? 0) + (nano.no_ticker ?? 0)} ({share(nano.no_ticker ?? 0, (nano.companies ?? 0) + (nano.no_ticker ?? 0))}) had no
              ticker by the time the study ran. Their filings are not in the averages.
            </p>
          )}
        </>
      }
    >
      <p className={styles.lede}>
        A database built from today&apos;s list of listed companies quietly removes the ones that failed. Any study run on it measures the
        winners and calls it the market.
      </p>

      <section className={styles.section}>
        <h2>How companies vanish</h2>
        <p>
          Small caps delist all the time: bankruptcy, reverse-merger shells, failing exchange listing rules, going private, being acquired.
          When that happens the ticker is reused or retired, and free price sources often drop the history. Afterfile samples companies by
          their SEC public float from a fixed past date (a point-in-time universe, so size is not chosen with hindsight), but it still needs
          a ticker today to fetch prices. Companies without one are counted as <code>no_ticker</code>; those with a ticker but no usable
          history as <code>no_prices</code>.
        </p>
      </section>

      <SurvivorshipSimulator />

      {study ? (
        <section className={styles.panel}>
          <h3>Coverage of the live event study</h3>
          <div className={styles.tableScroll}>
            <table className="data">
              <thead>
                <tr>
                  <th>Size</th>
                  <th>Sampled</th>
                  <th>No ticker now</th>
                  <th>No price data</th>
                  <th>With prices</th>
                </tr>
              </thead>
              <tbody>
                {BUCKETS.filter((b) => study.coverage[b]).map((b) => {
                  const c = study.coverage[b];
                  const sampled = (c.companies ?? 0) + (c.no_ticker ?? 0);
                  return (
                    <tr key={b}>
                      <td>{SIZE_LABELS[b] ?? b}</td>
                      <td>{sampled}</td>
                      <td>
                        {c.no_ticker ?? 0} <span className="muted">({share(c.no_ticker ?? 0, sampled)})</span>
                      </td>
                      <td>{c.no_prices ?? 0}</td>
                      <td>{c.with_prices ?? 0}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            <LiveTag kind="historical" date={study.generated_at} what="study generated" /> Size frame: {study.config.size_measured}. Window{" "}
            {study.config.window[0]} to {study.config.window[1]}.
          </p>
        </section>
      ) : (
        <ApiNote what="event study" status={main.ok ? 0 : main.status} />
      )}

      {bt ? (
        <section className={styles.panel}>
          <h3>Coverage of the backtest universe (priced offerings by nano caps)</h3>
          <div className={styles.tableScroll}>
            <table className="data">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Companies in size range</th>
                  <th>No ticker now</th>
                  <th>Offerings</th>
                  <th>Offerings without a ticker</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(bt.coverage).map(([k, c]) => (
                  <tr key={k}>
                    <td>{bt.periods[k]?.period.label ?? k}</td>
                    <td>{c.companies_in_size_range ?? "—"}</td>
                    <td>{c.no_ticker ?? "—"}</td>
                    <td>{c.offerings ?? "—"}</td>
                    <td>
                      {c.offerings_without_ticker ?? "—"}
                      {typeof c.offerings === "number" && typeof c.offerings_without_ticker === "number" && (
                        <span className="muted"> ({share(c.offerings_without_ticker, c.offerings)})</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            <LiveTag kind="hypothetical" date={bt.generated_at} what="backtest report" /> Compare the periods: the further back a sample starts, the
            more of its companies have had time to disappear.
          </p>
        </section>
      ) : (
        <ApiNote what="backtest report" status={report.ok ? 0 : report.status} />
      )}

      <section className={styles.section}>
        <h2>Which way does the bias point?</h2>
        <p>
          Usually it makes results look better than reality: the failures are missing. For signals that expect a decline it cuts both ways.
          The missing companies probably fell further, so measured declines are understated, yet those are exactly the stocks where a real
          short position would have faced recalls, forced closes and no shares to borrow. Either way the honest move is the same: report the
          coverage and do not round the bias away.
        </p>
      </section>
    </LessonLayout>
  );
}
