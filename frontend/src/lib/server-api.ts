// Server-side fetch helpers for server components, generateMetadata and sitemap.ts.
// Client components keep using `api` from ./api (cache: "no-store", browser base URL).
import { cache } from "react";

import type { Fundamentals, Halt, NewsletterIssue, NewsletterIssueSummary, SizeBucket, TickerDetail } from "./api";

// Environment variables (server-only module, so non-NEXT_PUBLIC names are readable here):
//   API_URL_INTERNAL      optional; API origin as seen from the Next server (e.g. http://backend:8000 in Docker).
//                         Falls back to NEXT_PUBLIC_API_URL, then http://localhost:8000.
//   NEXT_PUBLIC_API_URL   API origin as seen from the browser (also used by ./api); fallback for the above.
//   NEXT_PUBLIC_SITE_URL  public origin of this site (canonical, og:url, JSON-LD, sitemap, robots).
//                         Default http://localhost:3000 (a warning is logged in production).
//   PUBLIC_BASE_URL       same public origin as used by the backend newsletter; fallback when
//                         NEXT_PUBLIC_SITE_URL is unset, so one value can serve both. Must match if both are set.
// Where they come from: Next only loads frontend/.env, frontend/.env.local, frontend/.env.<mode>[.local]
// (or the real process environment). The repo-root .env is read by docker compose / the backend, NOT by
// Next, so a PUBLIC_BASE_URL set only there does not reach this module. NEXT_PUBLIC_* values are
// inlined at build time; the others are read at server runtime.

/** Base URL the Next server uses to reach the API (inside Docker this differs from the browser's URL). */
export const SERVER_API_BASE = (
  process.env.API_URL_INTERNAL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000"
).replace(/\/+$/, "");

const DEFAULT_SITE_URL = "http://localhost:3000";
const configuredSiteUrl = process.env.NEXT_PUBLIC_SITE_URL || process.env.PUBLIC_BASE_URL;

if (!configuredSiteUrl && process.env.NODE_ENV === "production") {
  console.warn(
    `[server-api] Neither NEXT_PUBLIC_SITE_URL nor PUBLIC_BASE_URL is set; canonical URLs, JSON-LD, ` +
      `sitemap.xml and robots.txt will point at ${DEFAULT_SITE_URL}.`,
  );
}

/** Public origin of this site, for canonical URLs, the sitemap and JSON-LD. No trailing slash. */
export const SITE_URL = (configuredSiteUrl || DEFAULT_SITE_URL).replace(/\/+$/, "");

export type Result<T> = { ok: true; data: T } | { ok: false; status: number; error: string };

async function getJson<T>(path: string, revalidate: number, timeoutMs: number): Promise<Result<T>> {
  try {
    const res = await fetch(`${SERVER_API_BASE}${path}`, {
      next: { revalidate },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) return { ok: false, status: res.status, error: `${res.status} ${res.statusText}` };
    return { ok: true, data: (await res.json()) as T };
  } catch (e) {
    // status 0 = network error or timeout (API down)
    return { ok: false, status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}

const enc = encodeURIComponent;

// React cache(): generateMetadata and the page share one request per render.
export const getTicker = cache((symbol: string, days = 90) =>
  getJson<TickerDetail>(`/api/tickers/${enc(symbol)}?days=${days}`, 900, 10_000),
);

export const getFundamentals = cache((symbol: string) =>
  getJson<Fundamentals>(`/api/tickers/${enc(symbol)}/fundamentals`, 900, 15_000),
);

export const getHalts = cache((symbol: string, hours = 8760) =>
  getJson<Halt[]>(`/api/halts?symbol=${enc(symbol)}&hours=${hours}`, 900, 10_000),
);

/** Row of GET /api/tickers/sitemap. */
export interface SitemapTicker {
  symbol: string;
  last_activity: string;
  items: number;
  size_bucket: SizeBucket | null;
}

export const getSitemapTickers = () => getJson<SitemapTicker[]>("/api/tickers/sitemap", 3600, 10_000);

// Newsletter. Archived issues are immutable once written (backend never overwrites without --force),
// so an issue is cached for a day; the list changes once a week (new issue on Monday).
// Non-2xx responses are not stored in the data cache, so an id that 404s now is fetched again later.
export const getNewsletterIssues = cache(() => getJson<NewsletterIssueSummary[]>("/api/newsletter/issues", 600, 10_000));

export const getNewsletterIssue = cache((id: string) => getJson<NewsletterIssue>(`/api/newsletter/${enc(id)}`, 86_400, 10_000));
