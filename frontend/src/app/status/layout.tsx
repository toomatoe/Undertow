import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "System status · QuantDesk",
  description: "Live health of QuantDesk's data pipeline: database, filing ingest, EDGAR poller, alerts, newsletter, 7-day uptime and track-record seal verification.",
};

export default function StatusLayout({ children }: { children: React.ReactNode }) {
  return children;
}
