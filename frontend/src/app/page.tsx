import type { Metadata } from "next";
import Link from "next/link";

import KeyFindings from "@/components/home/KeyFindings";
import { insiderFinding, offeringFinding, oosFinding } from "@/components/home/findings";
import styles from "@/components/home/home.module.css";
import { getEventStudy, SITE_URL } from "@/lib/server-api";

// Server-rendered landing page. The key findings are read from the API's study endpoints (1 h cache in
// server-api.ts); when the API is down or a study has not been run, each card shows a fallback sentence instead.
// Rendered per request: this app runs locally, and a build-time prerender would bake in "API not reachable"
// (the API is not running during `docker build`).
export const dynamic = "force-dynamic";

const TITLE = "Afterfile · small-cap SEC filing research, run locally";
const DESCRIPTION =
  "Afterfile is a local, personal research platform for SEC filings by small US companies: each live filing signal is shown next to its event-study evidence. It does not trade; simulated results are hypothetical and nothing here is investment advice.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: { type: "website", siteName: "Afterfile", url: "/", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

const QUICK_LINKS = [
  { href: "/news", title: "News", text: "Live feed of filings and market headlines" },
  { href: "/signals", title: "Signals", text: "Filing signals with their study evidence" },
  { href: "/track-record", title: "Track record", text: "Forward journal, sealed with a daily hash chain" },
  { href: "/paper", title: "Paper portfolio", text: "Hypothetical portfolio, no real orders" },
  { href: "/learn", title: "Learn", text: "Lessons on event studies and backtest pitfalls" },
];

export default async function Home() {
  const [main, oos, insider] = await Promise.all([getEventStudy("main"), getEventStudy("oos"), getEventStudy("insider_purchases")]);
  const findings = [offeringFinding(main), oosFinding(oos), insiderFinding(insider)];

  return (
    <main className={styles.page}>
      <section className={styles.hero} aria-labelledby="hero-title">
        <span className={styles.eyebrow}>Runs locally · research only</span>
        <h1 id="hero-title">SEC filings from small US companies, each shown next to the evidence on what happened after similar ones.</h1>
        <p className={styles.lead}>
          Afterfile is a personal research platform that runs on your own machine. It watches EDGAR for filings by companies under $2B of
          public float and puts every live signal beside an event study of how comparable stocks moved afterwards, including the results
          that did not hold up.
        </p>
        <ul className={styles.points}>
          <li>
            <strong>Local and personal.</strong> No accounts, no hosting; your data stays on this computer.
          </li>
          <li>
            <strong>Evidence first.</strong> Bonferroni-corrected, baseline-adjusted, judged after costs.
          </li>
          <li>
            <strong>Does not trade.</strong> No broker connection; the paper portfolio is hypothetical.
          </li>
        </ul>
        <div className={styles.actions}>
          <Link href="/research/paper" className={styles.primary}>
            Read the working paper
          </Link>
          <Link href="/signals" className={styles.secondary}>
            Browse live signals
          </Link>
          <Link href="/methodology" className={styles.secondary}>
            Methodology
          </Link>
        </div>
        <p className={styles.notAdvice}>
          General information about public filings and historical statistics only. Not investment advice. Simulated results are hypothetical.
        </p>
      </section>

      <KeyFindings findings={findings} />

      <section className={styles.paper} aria-labelledby="paper-cta">
        <div>
          <h2 id="paper-cta">The working paper</h2>
          <p className="muted">
            One in-sample event study, a pre-registered out-of-sample replication and a pre-registered Form 4 insider study, with every
            design choice and every failure written down.
          </p>
        </div>
        <Link href="/research/paper" className={styles.primary}>
          Read the working paper
        </Link>
      </section>

      <section className={styles.section} aria-labelledby="explore">
        <div className={styles.sectionHead}>
          <h2 id="explore">Explore</h2>
        </div>
        <nav className={styles.quick} aria-label="Quick links">
          {QUICK_LINKS.map((q) => (
            <Link key={q.href} href={q.href}>
              <strong>{q.title}</strong>
              <span>{q.text}</span>
            </Link>
          ))}
        </nav>
      </section>
    </main>
  );
}
