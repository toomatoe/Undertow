import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cloneElement } from "react";

import ArticleCard from "@/components/ArticleCard";
import { getFundamentals, getHalts, getTicker, SITE_URL } from "@/lib/server-api";

import { parseSymbol } from "./symbol";
import { lastModified, metaDescription, summarySentences, type TickerData } from "./summary";
import TickerView from "./TickerView";

// ISR: regenerate each ticker page at most every 15 minutes.
export const revalidate = 900;

const DAYS = 90;

type Params = Promise<{ symbol: string }>;

/** Ticker detail is required (404 -> notFound); fundamentals and halts are optional. */
async function load(raw: string): Promise<TickerData & { fundamentalsStatus: number | null; haltsStatus: number | null }> {
  const symbol = parseSymbol(raw);
  if (!symbol) notFound();
  const [t, f, h] = await Promise.all([getTicker(symbol, DAYS), getFundamentals(symbol), getHalts(symbol)]);
  if (!t.ok) {
    if (t.status === 404) notFound();
    throw new Error(`Ticker API unavailable (${t.error})`);
  }
  return {
    detail: t.data,
    fundamentals: f.ok ? f.data : null,
    halts: h.ok ? h.data : null,
    fundamentalsStatus: f.ok ? null : f.status,
    haltsStatus: h.ok ? null : h.status,
  };
}

function title(d: TickerData["detail"]): string {
  return `${d.symbol}${d.name ? ` – ${d.name}` : ""}: SEC filings, dilution & cash runway | Undertow`;
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { symbol } = await params;
  const data = await load(symbol);
  const t = title(data.detail);
  const description = metaDescription(data);
  const path = `/ticker/${encodeURIComponent(data.detail.symbol)}`;
  return {
    metadataBase: new URL(SITE_URL),
    title: t,
    description,
    alternates: { canonical: path },
    openGraph: { type: "website", siteName: "Undertow", url: path, title: t, description },
    twitter: { card: "summary", title: t, description },
  };
}

export default async function TickerPage({ params }: { params: Params }) {
  const { symbol } = await params;
  const data = await load(symbol);
  const d = data.detail;
  const url = `${SITE_URL}/ticker/${encodeURIComponent(d.symbol)}`;
  const modified = lastModified(data);
  // Anchor for the dated windows in the summary; fixed per ISR render, like the data it describes.
  const asOf = new Date();

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    "@id": url,
    url,
    name: title(d),
    description: metaDescription(data),
    ...(modified ? { dateModified: modified } : {}),
    about: {
      "@type": "Corporation",
      name: d.name ?? d.symbol,
      tickerSymbol: d.symbol,
    },
    isPartOf: { "@type": "WebSite", name: "Undertow", url: SITE_URL },
  };

  // Fundamentals: a 404 means no SEC company data, so the section is left out. Any other failure
  // (SEC or API briefly down) leaves it out of the server HTML and lets the client panel try again.
  const fundamentalsMode: "server" | "client" | "none" =
    !d.cik ? "none" : data.fundamentals ? "server" : data.fundamentalsStatus === 404 ? "none" : "client";

  return (
    <>
      <script
        type="application/ld+json"
        // "<" escaped so a company name can never close the script tag
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
      />
      <TickerView
        key={d.symbol}
        initial={d}
        initialDays={DAYS}
        fundamentals={data.fundamentals}
        fundamentalsMode={fundamentalsMode}
        halts={data.halts}
        summary={
          // Slots get keys: they arrive in the client component as lazy RSC elements inside its children array.
          <p key="summary" className="ticker-summary" data-testid="ticker-summary">
            {summarySentences(data, DAYS, asOf).join(" ")}
          </p>
        }
        // Rendered on the server so relative times ("3h ago") come from the RSC payload and never mismatch on hydration.
        initialArticles={
          <>
            {/* ArticleCard is a plain synchronous component (no hooks), called directly so the list holds
                inline keyed <article> elements. As <ArticleCard key/> each card becomes a separate lazy RSC
                chunk in dev and React warns about missing keys even though they are set. */}
            {d.articles.map((a) => cloneElement(ArticleCard({ article: a }), { key: a.id }))}
          </>
        }
        related={
          <nav key="related" className="panel related" aria-label="Related pages">
            <h2>Related</h2>
            <ul>
              <li>
                <Link href="/signals">Latest small-cap filing signals</Link>
              </li>
              <li>
                <Link href="/track-record">Signal track record</Link>
              </li>
              <li>
                <Link href="/lab">Edge Lab event-study results</Link>
              </li>
              <li>
                <Link href="/methodology">How these numbers are produced</Link>
              </li>
            </ul>
          </nav>
        }
      />
    </>
  );
}
