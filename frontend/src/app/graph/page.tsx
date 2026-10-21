import type { Metadata } from "next";
import { Suspense } from "react";

import GraphExplorer, { GraphSkeleton } from "@/components/graph/GraphExplorer";

export const metadata: Metadata = {
  title: "Event graph · Undertow",
  description:
    "Recent SEC filings and market news drawn as a graph of related events: clusters, how they grew over time, and their mood. Links show association, not cause and effect. Research only, not investment advice.",
};

/** /graph: thin server wrapper (metadata); the interactive graph is the client <GraphExplorer/> (reads ?ticker=&days=&source=). */
export default function GraphPage() {
  return (
    <main className="page wide">
      <h1>Event graph</h1>
      <p className="lede muted">
        Recent filings and news as a network: items with similar text, the same company or size, or close publication times are
        linked, and tightly linked groups form clusters. Replay the window to watch clusters form. Links show association, not cause
        and effect. Research and education only.
      </p>
      {/* useSearchParams needs a Suspense boundary for static rendering */}
      <Suspense fallback={<GraphSkeleton />}>
        <GraphExplorer />
      </Suspense>
    </main>
  );
}
