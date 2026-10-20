import type { Metadata } from "next";
import Link from "next/link";

import { SITE_URL } from "@/lib/server-api";

import styles from "./research.module.css";

// Static server component (no API calls): index of Afterfile's published research.
const TITLE = "Research · Afterfile";
const DESCRIPTION =
  "Afterfile research: a working paper on SEC filing events and small-cap returns, the Edge Lab event studies (in-sample, pre-registered out-of-sample, Form 4 insider purchases) and their pre-registrations.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/research" },
  openGraph: { type: "website", siteName: "Afterfile", url: "/research", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

const STUDIES = [
  {
    study: "main",
    title: "In-sample event study (2023-26)",
    text: "Every filing signal by size bucket and horizon, after a Bonferroni correction, an ordinary-day baseline and assumed costs. The live evidence behind each signal card.",
  },
  {
    study: "oos",
    title: "Pre-registered out-of-sample replication (2020-23)",
    text: "Three in-sample leads retested on earlier years and companies the first study never sampled, with verdicts fixed in advance.",
  },
  {
    study: "insider_purchases",
    title: "Form 4 insider purchases (pre-registered)",
    text: "Open-market purchases by directors and officers, including cluster purchases and opportunistic vs routine insiders.",
  },
] as const;

const PREREGISTRATIONS = [
  { path: "backend/app/research/PREREGISTRATION_OOS.md", what: "out-of-sample replication (registered 2026-10-19)" },
  { path: "backend/app/insiders/PREREGISTRATION.md", what: "Form 4 insider-purchase study (registered 2026-10-19)" },
];

export default function ResearchPage() {
  return (
    <main className={`page ${styles.page}`}>
      <h1>Research</h1>
      <p className="muted">
        What Afterfile&apos;s data says about SEC filings and small-cap returns, written up with its methods and failures. Event-study numbers
        are historical averages; net and backtest numbers are hypothetical. Nothing here is investment advice.
      </p>

      <section aria-labelledby="paper">
        <h2 id="paper" className={styles.sectionTitle}>
          Working paper
        </h2>
        <Link href="/research/paper" className={styles.feature}>
          <span className={styles.kicker}>Working paper · October 2026</span>
          <span className={styles.featureTitle}>
            Do SEC filing events predict small-cap returns? Evidence from an in-sample event study, a pre-registered out-of-sample
            replication, and Form 4 insider purchases
          </span>
          <span className={styles.featureText}>
            The nano-cap offering drift that passed in-sample did not replicate net of costs and borrow out of sample; micro-cap insider
            cluster purchases passed their pre-registered test but leave little after costs. Every headline number is checked automatically
            against the published result files.
          </span>
          <span className={styles.cta}>Read the working paper</span>
        </Link>
      </section>

      <section aria-labelledby="studies">
        <h2 id="studies" className={styles.sectionTitle}>
          Edge Lab studies
        </h2>
        <ul className={styles.cards}>
          {STUDIES.map((s) => (
            <li key={s.study}>
              <Link href={s.study === "main" ? "/lab" : `/lab?study=${s.study}`} className={styles.card}>
                <span className={styles.cardTitle}>{s.title}</span>
                <span className={styles.cardText}>{s.text}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="muted small">
          The strategy simulation built on the offering result is on the <Link href="/backtest">Backtest</Link> page (hypothetical, not
          tradable as specified).
        </p>
      </section>

      <section aria-labelledby="prereg">
        <h2 id="prereg" className={styles.sectionTitle}>
          Pre-registrations
        </h2>
        <p className="muted small">Written and committed before the studies they describe were run. Paths in the project repository:</p>
        <ul className={styles.paths}>
          {PREREGISTRATIONS.map((p) => (
            <li key={p.path}>
              <code>{p.path}</code>
              <span className="muted small"> {p.what}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
