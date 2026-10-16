import { notFound } from "next/navigation";

import { getTicker } from "@/lib/server-api";

import { parseSymbol } from "./symbol";

/**
 * Resolves the ticker before anything streams, so an unknown symbol gets a real HTTP 404.
 * (loading.tsx wraps only the page below; a notFound() thrown there would arrive after a 200 header.)
 * The (view) route group exists so ../not-found.tsx can catch the notFound() thrown here.
 * getTicker is wrapped in React cache(), so the page reuses this request.
 * A param that cannot be a ticker (malformed escape, odd characters) is a 404 without an API call.
 */
export default async function TickerLayout({ children, params }: { children: React.ReactNode; params: Promise<{ symbol: string }> }) {
  const symbol = parseSymbol((await params).symbol);
  if (!symbol) notFound();
  const t = await getTicker(symbol, 90);
  if (!t.ok && t.status === 404) notFound();
  return children;
}
