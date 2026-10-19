// Server component: the frame every lesson shares (JSON-LD, header, "What this means for QuantDesk",
// "Read the code", readings, disclaimer, previous/next).

import Link from "next/link";
import type { ReactNode } from "react";

import { CURRICULUM_PATH, LESSONS, LESSONS_REVISED, lessonPath, type Lesson } from "@/lib/learn/lessons";
import { SITE_URL } from "@/lib/server-api";

import styles from "./learn.module.css";
import { Disclaimer, JsonLd, Readings, RepoRefs } from "./parts";

export default function LessonLayout({
  lesson,
  meaning,
  dataDate,
  children,
}: {
  lesson: Lesson;
  /** "What this means for QuantDesk" body. */
  meaning: ReactNode;
  /** Newest generated_at among the live documents shown (dateModified), if any loaded. */
  dataDate: string | null;
  children: ReactNode;
}) {
  const url = `${SITE_URL}${lessonPath(lesson.slug)}`;
  const i = LESSONS.findIndex((l) => l.slug === lesson.slug);
  const prev = i > 0 ? LESSONS[i - 1] : null;
  const next = i >= 0 && i < LESSONS.length - 1 ? LESSONS[i + 1] : null;
  const modified = dataDate && dataDate > LESSONS_REVISED ? dataDate : LESSONS_REVISED;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    "@id": url,
    url,
    mainEntityOfPage: url,
    headline: lesson.title,
    description: lesson.description,
    datePublished: LESSONS_REVISED,
    dateModified: modified,
    inLanguage: "en",
    isAccessibleForFree: true,
    learningResourceType: "Lesson",
    educationalLevel: lesson.level,
    timeRequired: `PT${lesson.minutes}M`,
    keywords: lesson.concepts.join(", "),
    citation: lesson.readings.map((r) => `${r.cite}. ${r.title}. ${r.venue}.`),
    author: { "@type": "Organization", name: "QuantDesk", url: SITE_URL },
    publisher: { "@type": "Organization", name: "QuantDesk", url: SITE_URL },
    isPartOf: { "@type": "Course", name: "QuantDesk Learn", url: `${SITE_URL}/learn` },
  };

  return (
    <main className={`page ${styles.page}`}>
      <JsonLd data={jsonLd} />
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/learn">Learn</Link> / {lesson.title.split(":")[0]}
      </nav>
      <header className={styles.section}>
        <h1>{lesson.title}</h1>
        <div className={styles.meta}>
          <span>{lesson.level}</span>·<span>{lesson.minutes} min</span>·
          {lesson.concepts.map((c) => (
            <span key={c} className={styles.chip}>
              {c}
            </span>
          ))}
        </div>
      </header>

      {children}

      <section className={styles.section}>
        <h2>What this means for QuantDesk</h2>
        {meaning}
      </section>

      <section className={styles.section}>
        <h2>Read the code</h2>
        <RepoRefs refs={lesson.repoRefs} />
        <p className="muted small">
          Try it: change one of these in a branch and run <code>bash scripts/pytest.sh</code> with the matching test file. The{" "}
          <Link href={CURRICULUM_PATH}>8-week curriculum</Link> has exercises for each.
        </p>
      </section>

      <section className={styles.section}>
        <h2>Further reading</h2>
        <Readings items={lesson.readings} />
      </section>

      <nav className={styles.pager} aria-label="More lessons">
        <span>{prev && <Link href={lessonPath(prev.slug)}>← {prev.title.split(":")[0]}</Link>}</span>
        <span>{next ? <Link href={lessonPath(next.slug)}>{next.title.split(":")[0]} →</Link> : <Link href={CURRICULUM_PATH}>Curriculum →</Link>}</span>
      </nav>
      <Disclaimer />
    </main>
  );
}
