import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "System status · Undertow",
  description: "Live health of Undertow's data pipeline: database, filing ingest, EDGAR poller, alerts, newsletter, 7-day uptime and track-record seal verification.",
};

export default function StatusLayout({ children }: { children: React.ReactNode }) {
  return children;
}
