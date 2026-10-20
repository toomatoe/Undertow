import type { Metadata } from "next";

// Metadata for the client page in this folder (a "use client" page cannot export metadata).
export const metadata: Metadata = {
  title: "Backtest (hypothetical) · Undertow",
  description: "Simulated, hypothetical portfolio backtest of the filing signals with costs, borrow fees, readiness gates and the run log. No real trades, not investment advice.",
};

export default function BacktestLayout({ children }: { children: React.ReactNode }) {
  return children;
}
