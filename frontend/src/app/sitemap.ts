import type { MetadataRoute } from "next";

import { issuePath } from "@/components/newsletter/format";
import { getNewsletterIssues, getSitemapTickers, SITE_URL } from "@/lib/server-api";

export const revalidate = 3600;

const STATIC_PAGES: { path: string; changeFrequency: "hourly" | "daily" | "weekly" | "monthly"; priority: number }[] = [
  { path: "/", changeFrequency: "hourly", priority: 1 },
  { path: "/signals", changeFrequency: "hourly", priority: 0.9 },
  { path: "/track-record", changeFrequency: "daily", priority: 0.8 },
  { path: "/lab", changeFrequency: "weekly", priority: 0.7 },
  { path: "/backtest", changeFrequency: "weekly", priority: 0.6 },
  { path: "/methodology", changeFrequency: "monthly", priority: 0.6 },
  { path: "/newsletter", changeFrequency: "weekly", priority: 0.6 },
  { path: "/legal/disclaimer", changeFrequency: "monthly", priority: 0.2 },
  { path: "/legal/terms", changeFrequency: "monthly", priority: 0.2 },
  { path: "/legal/privacy", changeFrequency: "monthly", priority: 0.2 },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const pages: MetadataRoute.Sitemap = STATIC_PAGES.map((p) => ({
    url: `${SITE_URL}${p.path === "/" ? "" : p.path}`,
    changeFrequency: p.changeFrequency,
    priority: p.priority,
  }));

  // Ticker and newsletter pages; if the API is down (each helper returns ok: false, never throws)
  // the static pages are still served.
  const [tickers, issues] = await Promise.all([getSitemapTickers(), getNewsletterIssues()]);
  if (tickers.ok) {
    for (const t of tickers.data) {
      const last = new Date(t.last_activity);
      pages.push({
        url: `${SITE_URL}/ticker/${encodeURIComponent(t.symbol.toUpperCase())}`,
        ...(Number.isNaN(last.getTime()) ? {} : { lastModified: last }),
        changeFrequency: "daily",
        priority: 0.5,
      });
    }
  }
  // Archived newsletter issues are immutable once built.
  if (issues.ok) {
    for (const i of issues.data) {
      const generated = new Date(i.generated_at);
      pages.push({
        url: `${SITE_URL}${issuePath(i.id)}`,
        ...(Number.isNaN(generated.getTime()) ? {} : { lastModified: generated }),
        changeFrequency: "yearly",
        priority: 0.5,
      });
    }
  }
  return pages;
}
