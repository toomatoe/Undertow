import { notFound } from "next/navigation";

import { parseIssueId } from "@/components/newsletter/format";
import { getNewsletterIssue } from "@/lib/server-api";

/**
 * Resolves the issue before anything streams, so an unknown id gets a real HTTP 404
 * (same gate as app/ticker/[symbol]/(view)/layout.tsx: loading.tsx wraps only the page below, and a
 * notFound() thrown there would arrive after a 200 header). The (view) route group exists so
 * ../not-found.tsx catches the notFound() thrown here. getNewsletterIssue is wrapped in React cache(),
 * so the page and generateMetadata reuse this request. A param that is not an ISO-week id is a 404
 * without an API call.
 */
export default async function IssueLayout({ children, params }: { children: React.ReactNode; params: Promise<{ issue: string }> }) {
  const id = parseIssueId((await params).issue);
  if (!id) notFound();
  const r = await getNewsletterIssue(id);
  if (!r.ok && r.status === 404) notFound();
  return children;
}
