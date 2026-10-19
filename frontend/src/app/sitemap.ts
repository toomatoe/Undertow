import type { MetadataRoute } from "next";

import { issuePath } from "@/components/newsletter/format";
import { CURRICULUM_PATH, LESSONS, lessonPath } from "@/lib/learn/lessons";
import { getNewsletterIssues, getSitemapTickers, SITE_URL } from "@/lib/server-api";

// Rendered per request: this app runs locally, and a build-time prerender would bake in "API not reachable"
// (the API is not running during `docker build`).
export const dynamic = "force-dynamic";

const STATIC_PAGES: { path: string; changeFrequency: "hourly" | "daily" | "weekly" | "monthly"; priority: number }[] = [
  { path: "/", changeFrequency: "daily", priority: 1 },
  { path: "/news", changeFrequency: "hourly", priority: 0.9 },
  { path: "/signals", changeFrequency: "hourly", priority: 0.9 },
  { path: "/track-record", changeFrequency: "daily", priority: 0.8 },
  { path: "/lab", changeFrequency: "weekly", priority: 0.7 },
  { path: "/backtest", changeFrequency: "weekly", priority: 0.6 },
  { path: "/paper", changeFrequency: "daily", priority: 0.7 },
  { path: "/research", changeFrequency: "monthly", priority: 0.7 },
  { path: "/research/paper", changeFrequency: "monthly", priority: 0.8 },
  { path: "/methodology", changeFrequency: "monthly", priority: 0.6 },
  { path: "/newsletter", changeFrequency: "weekly", priority: 0.6 },
  { path: "/learn", changeFrequency: "weekly", priority: 0.7 },
  ...LESSONS.map((l) => ({ path: lessonPath(l.slug), changeFrequency: "monthly" as const, priority: 0.6 })),
  { path: CURRICULUM_PATH, changeFrequency: "monthly", priority: 0.6 },
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
