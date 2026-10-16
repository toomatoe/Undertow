import type { Metadata } from "next";

import NewsletterWorkspace from "@/components/newsletter/NewsletterWorkspace";
import { getNewsletterIssue, getNewsletterIssues, SITE_URL } from "@/lib/server-api";

// ISR: the archive gains one issue a week; 10 minutes keeps a fresh issue from lagging long.
export const revalidate = 600;

// Title and description come from ./layout.tsx.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  alternates: { canonical: "/newsletter" },
};

/**
 * Archive: server-rendered list of issue links (crawlable) plus the latest issue inline.
 * If the API is down the page still renders and the client workspace retries.
 * Keep this a server component that fetches via lib/server-api.ts. A "use client" page fetching in
 * useEffect (the older pattern for data pages) would hide the issue links from crawlers.
 */
export default async function NewsletterPage() {
  const list = await getNewsletterIssues();
  const issues = list.ok ? list.data : null;
  const latest = issues?.[0] ? await getNewsletterIssue(issues[0].id) : null;

  return (
    <main className="page wide nl">
      <div>
        <h1>Small-Cap Filing Radar</h1>
        <p className="nl-intro">
          A weekly newsletter of the week&apos;s most serious SEC filings from companies under $2B public float, dilution warnings, trading halts and
          how our forward track record is developing.
        </p>
        <p className="muted small">
          <strong>Generated automatically every Monday from public SEC/FINRA/Nasdaq data.</strong> Impersonal facts and historical statistics; every
          Edge Lab, backtest and track-record figure is historical or hypothetical. Not investment advice.
        </p>
      </div>

      <NewsletterWorkspace issues={issues} issue={latest?.ok ? latest.data : null} legacyQuery />
    </main>
  );
}
