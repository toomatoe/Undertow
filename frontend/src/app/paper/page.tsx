import type { Metadata } from "next";

import PaperPortfolioView from "@/components/portfolio/PaperPortfolioView";

export const metadata: Metadata = {
  title: "Paper portfolio (hypothetical) · QuantDesk",
  description:
    "A hypothetical, simulated portfolio built from the forward signal journal, with estimated costs and borrow fees. Not traded, not investment advice.",
};

/** Server shell; the simulation is fetched in the client island (same data pattern as /track-record). */
export default function PaperPage() {
  return <PaperPortfolioView />;
}
