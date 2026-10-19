import type { Metadata } from "next";

import NewsFeed from "@/components/NewsFeed";
import { SITE_URL } from "@/lib/server-api";

// /news: the live market news and filing feed (moved here from / when / became the landing page).
// NewsFeed is a client component (filters, pagination, SSE); this wrapper only adds metadata.
const TITLE = "News · QuantDesk";
const DESCRIPTION = "Live feed of SEC filings and market headlines for small US companies, with filters by size, source, sentiment and event type.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/news" },
  openGraph: { type: "website", siteName: "QuantDesk", url: "/news", title: TITLE, description: DESCRIPTION },
};

export default function NewsPage() {
  return (
    <>
      <h1 className="sr-only">News: SEC filings and market headlines</h1>
      <NewsFeed />
    </>
  );
}
