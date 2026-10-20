import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { issueDescription, issuePath, issueTitle, parseIssueId, weekLabel } from "@/components/newsletter/format";
import NewsletterWorkspace from "@/components/newsletter/NewsletterWorkspace";
import type { NewsletterIssue } from "@/lib/api";
import { getNewsletterIssue, getNewsletterIssues, SITE_URL } from "@/lib/server-api";

// Archived issues never change, so the data is cached for a day (server-api). The page itself is
// regenerated hourly so the archive sidebar picks up new issues and a 404 for a not-yet-built week clears.
export const revalidate = 3600;
// Server-rendered for crawlers (metadata, canonical, JSON-LD); do not convert to a useEffect client page.
// The 404 gate lives in ./layout.tsx (same pattern as app/ticker/[symbol]/(view)).

type Params = Promise<{ issue: string }>;

/** Issue is required (404 -> notFound, the layout already checked); the archive list is optional. */
async function load(raw: string): Promise<NewsletterIssue> {
  const id = parseIssueId(raw);
  if (!id) notFound();
  const r = await getNewsletterIssue(id);
  if (!r.ok) {
    if (r.status === 404) notFound();
    throw new Error(`Newsletter API unavailable (${r.error})`);
  }
  return r.data;
}

/** Publication date: when the issue was generated, else the end of its week. */
function published(issue: NewsletterIssue): string {
  const g = new Date(issue.generated_at);
  return Number.isNaN(g.getTime()) ? issue.week_end : g.toISOString();
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const issue = await load((await params).issue);
  const title = issueTitle(issue);
  const description = issueDescription(issue);
  const path = issuePath(issue.id);
  return {
    metadataBase: new URL(SITE_URL),
    title: { absolute: title },
    description,
    alternates: { canonical: path },
    openGraph: { type: "article", siteName: "Undertow", url: path, title, description, publishedTime: published(issue) },
    twitter: { card: "summary", title, description },
  };
}

export default async function IssuePage({ params }: { params: Params }) {
  const { issue: raw } = await params;
  const [issue, list] = await Promise.all([load(raw), getNewsletterIssues()]);
  const url = `${SITE_URL}${issuePath(issue.id)}`;
  const date = published(issue);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    "@id": url,
    url,
    mainEntityOfPage: url,
    headline: `Small-Cap Filing Radar: ${weekLabel(issue)}`,
    description: issueDescription(issue),
    datePublished: date,
    dateModified: date,
    temporalCoverage: `${issue.week_start}/${issue.week_end}`,
    inLanguage: "en",
    isAccessibleForFree: true,
    author: { "@type": "Organization", name: "Undertow", url: SITE_URL },
    publisher: { "@type": "Organization", name: "Undertow", url: SITE_URL },
    isPartOf: { "@type": "CreativeWorkSeries", name: "Small-Cap Filing Radar", url: `${SITE_URL}/newsletter` },
  };

  return (
    <main className="page wide nl">
      <script
        type="application/ld+json"
        // "<" escaped so no string in the issue can close the script tag
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
      />
      <div>
        <Link href="/newsletter" className="back">
          ← Newsletter archive
        </Link>
        <h1>Small-Cap Filing Radar: {weekLabel(issue)}</h1>
        <p className="muted small">
          <strong>{issue.sources_note || "Generated automatically from public SEC/FINRA/Nasdaq data."}</strong> Impersonal facts and historical statistics; every Edge Lab, backtest and track-record figure is historical
          or hypothetical. Not investment advice.
        </p>
      </div>

      <NewsletterWorkspace key={issue.id} issues={list.ok ? list.data : null} issue={issue} />
    </main>
  );
}
