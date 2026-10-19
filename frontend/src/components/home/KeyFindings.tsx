import Link from "next/link";

import { type Finding, studyDate } from "./findings";
import styles from "./home.module.css";

/** Server-rendered "Key findings" cards on the landing page. Numbers come from the API (see findings.ts). */
export default function KeyFindings({ findings }: { findings: Finding[] }) {
  return (
    <section aria-labelledby="key-findings" className={styles.section}>
      <div className={styles.sectionHead}>
        <h2 id="key-findings">Key findings</h2>
        <p className="muted small">
          Read live from this machine&apos;s study files. Drift figures are historical, market-adjusted averages; net figures are hypothetical
          and depend on assumed costs and borrow.
        </p>
      </div>
      <div className={styles.cards}>
        {findings.map((f) => {
          const date = studyDate(f);
          return (
            <article key={f.key} className={styles.card}>
              <span className={styles.kicker}>{f.kicker}</span>
              <span className={f.value ? styles.value : `${styles.value} ${styles.valueMissing}`}>{f.value ?? "Not available"}</span>
              <p className={styles.cardText}>{f.text}</p>
              <span className={styles.labels}>
                {f.labels.map((l) => (
                  <span key={l} className={styles.label}>
                    {l}
                  </span>
                ))}
                {date && <span className={styles.date}>study run {date}</span>}
              </span>
              <span className={styles.cardLinks}>
                <Link href={f.href}>{f.linkLabel}</Link>
                <Link href="/research/paper">In the paper</Link>
              </span>
            </article>
          );
        })}
      </div>
    </section>
  );
}
