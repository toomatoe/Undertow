import type { Metadata } from "next";

// Metadata for the client page in this folder (a "use client" page cannot export metadata).
export const metadata: Metadata = {
  title: "Filing signals · Afterfile",
  description: "Live SEC filing signals for companies under $2B public float, each with the historical event-study evidence for its signal and size bucket. Research only, not investment advice.",
};

export default function SignalsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
