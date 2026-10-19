import type { Metadata } from "next";

// Metadata for the client page in this folder (a "use client" page cannot export metadata).
export const metadata: Metadata = {
  title: "Track record (hypothetical) · QuantDesk",
  description: "Forward journal of every filing signal, priced after the fact and sealed with a daily hash chain. Simulated tracking: results are hypothetical, no trades, not investment advice.",
};

export default function TrackRecordLayout({ children }: { children: React.ReactNode }) {
  return children;
}
