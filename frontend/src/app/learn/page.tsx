import type { Metadata } from "next";
import Link from "next/link";

import styles from "@/components/learn/learn.module.css";
import { Disclaimer, JsonLd } from "@/components/learn/parts";
import { CURRICULUM } from "@/lib/learn/curriculum";
import { CURRICULUM_PATH, LESSONS, lessonPath, LESSONS_REVISED } from "@/lib/learn/lessons";
import { SITE_URL } from "@/lib/server-api";

// Static server component (no API calls): the lesson list and curriculum, crawlable.
const TITLE = "Learn quant research with real small-cap data · Afterfile";
const DESCRIPTION =
  "Free lessons on event studies, baselines, multiple testing, clustered errors, survivorship bias and the deflated Sharpe ratio, each tied to Afterfile's own code and data.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/learn" },
  openGraph: { type: "website", siteName: "Afterfile", url: "/learn", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

export default function LearnIndex() {
  const url = `${SITE_URL}/learn`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Course",
    "@id": url,
    url,
    name: "Afterfile Learn",
    description: DESCRIPTION,
    inLanguage: "en",
    isAccessibleForFree: true,
    dateModified: LESSONS_REVISED,
    provider: { "@type": "Organization", name: "Afterfile", url: SITE_URL },
    hasPart: LESSONS.map((l) => ({
      "@type": "Article",
      headline: l.title,
      description: l.description,
      url: `${SITE_URL}${lessonPath(l.slug)}`,
    })),
  };

  return (
    <main className={`page ${styles.page}`}>
      <JsonLd data={jsonLd} />
      <header className={styles.section}>
        <h1>Learn</h1>
        <p className={styles.lede}>
          How to tell a real pattern in market data from a lucky one. Each lesson explains one idea, lets you run a small simulation in your
          browser, shows Afterfile&apos;s own live numbers with their dates, and points to the exact file and function in this project that
          implements it.
        </p>
      </header>

      <section className={styles.section} aria-labelledby="lessons">
        <h2 id="lessons">Lessons</h2>
        <div className={styles.cards}>
          {LESSONS.map((l, i) => (
            <Link key={l.slug} href={lessonPath(l.slug)} className={styles.card}>
              <span className="muted small">
                {i + 1}. {l.level} · {l.minutes} min
              </span>
              <h3>{l.title}</h3>
              <span className="small">{l.description}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="curriculum">
        <h2 id="curriculum">8-week curriculum</h2>
        <p>
          A self-study path for a student quant developer: each week pairs concepts with the repo files to read, an exercise that changes
          code and runs the tests, and the canonical papers. <Link href={CURRICULUM_PATH}>Open the curriculum</Link>.
        </p>
        <ol>
          {CURRICULUM.map((w) => (
            <li key={w.week}>
              <strong>Week {w.week}:</strong> {w.title}
            </li>
          ))}
        </ol>
      </section>

      <p className="muted small">
        Live numbers on lesson pages are labelled <em>historical</em> (measured on past filings) or <em>hypothetical</em> (simulated trading or
        random simulations), each with the date it was generated.
      </p>
      <Disclaimer />
    </main>
  );
}
