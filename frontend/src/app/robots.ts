import type { MetadataRoute } from "next";

import { isLocalSiteUrl, SITE_URL } from "@/lib/server-api";

export default function robots(): MetadataRoute.Robots {
  // QuantDesk runs locally by default: with a localhost site origin nothing is public, so ask crawlers to stay out.
  // The sitemap link is still served so /sitemap.xml stays discoverable for local checks.
  if (isLocalSiteUrl()) {
    return {
      rules: { userAgent: "*", disallow: "/" },
      sitemap: `${SITE_URL}/sitemap.xml`,
    };
  }
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
