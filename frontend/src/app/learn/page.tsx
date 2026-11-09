import type { Metadata } from "next";
import Link from "next/link";

import styles from "@/components/learn/learn.module.css";
import homeStyles from "@/components/home/home.module.css";
import { Disclaimer, JsonLd } from "@/components/learn/parts";
import { CURRICULUM } from "@/lib/learn/curriculum";
import { CURRICULUM_PATH, LESSONS, lessonPath, LESSONS_REVISED } from "@/lib/learn/lessons";
import { SITE_URL } from "@/lib/server-api";

// Static server component (no API calls): the lesson list and curriculum, crawlable.
const TITLE = "Learn to read company filings and research · Undertow";
const DESCRIPTION =
  "Start with a hands-on beginner tutorial, then explore lessons on company filings, historical comparisons and research pitfalls.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/learn" },
  openGraph: { type: "website", siteName: "Undertow", url: "/learn", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

export default function LearnIndex() {
  const url = `${SITE_URL}/learn`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Course",
    "@id": url,
    url,
    name: "Undertow Learn",
    description: DESCRIPTION,
    inLanguage: "en",
    isAccessibleForFree: true,
    dateModified: LESSONS_REVISED,
    provider: { "@type": "Organization", name: "Undertow", url: SITE_URL },
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
          Start with the basics, then go deeper at your own pace. No finance or coding background is needed for the beginner tutorial.
        </p>
      </header>

      <section className={homeStyles.paper} aria-labelledby="beginner-tutorial">
        <div>
          <span className="muted small">NEW HERE? · ABOUT 5 MINUTES</span>
          <h2 id="beginner-tutorial">Your first filing, step by step</h2>
          <p>Explore a fictional company report, try a simple comparison, and learn what the numbers can and cannot tell you. Works without live data.</p>
        </div>
        <a href="/tutorial.html" className={homeStyles.secondary}>Start the interactive tutorial</a>
      </section>

      <section className={styles.section} aria-labelledby="lessons">
        <h2 id="lessons">Go deeper: research lessons</h2>
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
