import type { Metadata } from "next";
import Link from "next/link";

import styles from "@/components/learn/learn.module.css";
import { Disclaimer, JsonLd, Readings, RepoRefs } from "@/components/learn/parts";
import { CURRICULUM } from "@/lib/learn/curriculum";
import { CURRICULUM_PATH, getLesson, lessonPath, LESSONS_REVISED } from "@/lib/learn/lessons";
import { SITE_URL } from "@/lib/server-api";

// Static server component: no API calls.
const TITLE = "8-week quant research curriculum for student developers · Afterfile Learn";
const DESCRIPTION =
  "A self-study path through event studies, multiple testing, clustered errors, pre-registration, Form 4 parsing and the deflated Sharpe ratio, with code exercises and readings.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: CURRICULUM_PATH },
  openGraph: { type: "article", siteName: "Afterfile", url: CURRICULUM_PATH, title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

export default function CurriculumPage() {
  const url = `${SITE_URL}${CURRICULUM_PATH}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    "@id": url,
    url,
    mainEntityOfPage: url,
    headline: "8-week quant research curriculum",
    description: DESCRIPTION,
    datePublished: LESSONS_REVISED,
    dateModified: LESSONS_REVISED,
    inLanguage: "en",
    isAccessibleForFree: true,
    learningResourceType: "Syllabus",
    timeRequired: "P8W",
    author: { "@type": "Organization", name: "Afterfile", url: SITE_URL },
    publisher: { "@type": "Organization", name: "Afterfile", url: SITE_URL },
    isPartOf: { "@type": "Course", name: "Afterfile Learn", url: `${SITE_URL}/learn` },
  };

  return (
    <main className={`page ${styles.page}`}>
      <JsonLd data={jsonLd} />
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/learn">Learn</Link> / Curriculum
      </nav>
      <header className={styles.section}>
        <h1>8-week quant research curriculum</h1>
        <p className={styles.lede}>
          For a student developer who wants to learn empirical finance by working on a real codebase. Each week: the ideas, the files in
          this repo that implement them, one exercise that changes code and runs the tests, and the papers to read.
        </p>
        <p className="small">
          Setup: Python is not needed on your machine. Backend tests run in Docker against your working copy with{" "}
          <code>bash scripts/pytest.sh tests/test_eventstudy.py</code> (any test file). Do the exercises in a throwaway branch: several of
          them deliberately break a pre-registered design to show that the tests catch it.
        </p>
      </header>

      {CURRICULUM.map((w) => (
        <section key={w.week} className={`${styles.section} ${styles.week}`} aria-labelledby={`week-${w.week}`}>
          <h2 id={`week-${w.week}`}>
            Week {w.week}: {w.title}
          </h2>
          <p>{w.goal}</p>
          <div className={styles.meta}>
            {w.concepts.map((c) => (
              <span key={c} className={styles.chip}>
                {c}
              </span>
            ))}
          </div>
          {w.lessons.length > 0 && (
            <p className="small">
              Lesson{w.lessons.length > 1 ? "s" : ""}:{" "}
              {w.lessons.map((s, i) => {
                const l = getLesson(s);
                return l ? (
                  <span key={s}>
                    {i > 0 && ", "}
                    <Link href={lessonPath(s)}>{l.title.split(":")[0]}</Link>
                  </span>
                ) : null;
              })}
            </p>
          )}
          <h3>Read</h3>
          <RepoRefs refs={w.read} />
          <h3>Exercise</h3>
          <p>{w.exercise.task}</p>
          <p className={styles.code}>{w.exercise.command}</p>
          <p className="muted small">Look for: {w.exercise.lookFor}</p>
          <h3>Readings</h3>
          <Readings items={w.readings} />
        </section>
      ))}

      <p className="muted small">Citations only; read the papers from the publisher or your library.</p>
      <Disclaimer />
    </main>
  );
}
