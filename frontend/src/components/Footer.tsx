"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { isAdminApiError } from "@/lib/api";

/**
 * Site-wide footer (in layout.tsx). Also the safety net for admin-protected calls whose caller forgot a catch:
 * an unhandled 401/403/429 ApiError is shown here as a dismissible alert instead of failing silently.
 * Callers that catch their own errors (WatchlistPanel, ResearchRunPanel, Sidebar, TickerView, /status) never reach this.
 */
export default function Footer() {
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const onRejection = (ev: PromiseRejectionEvent) => {
      if (!isAdminApiError(ev.reason)) return;
      ev.preventDefault(); // handled here: no "Uncaught (in promise)" console error
      setNotice(ev.reason.message.replace(/^\d{3}\s+/, ""));
    };
    window.addEventListener("unhandledrejection", onRejection);
    return () => window.removeEventListener("unhandledrejection", onRejection);
  }, []);

  return (
    <footer className="site-footer">
      {notice && (
        <div
          role="alert"
          style={{
            position: "fixed",
            left: 16,
            right: 16,
            bottom: 16,
            zIndex: 50,
            maxWidth: 560,
            margin: "0 auto",
            display: "flex",
            gap: 12,
            alignItems: "center",
            padding: "10px 14px",
            background: "var(--panel)",
            border: "1px solid var(--border)",
            borderRadius: 8,
          }}
        >
          <span style={{ flex: 1 }}>
            {notice} <Link href="/status">Open Status</Link>
          </span>
          <button className="btn" onClick={() => setNotice(null)} aria-label="Dismiss">
            Dismiss
          </button>
        </div>
      )}
      <p>
        Undertow shows general information about public filings and historical statistics. It is not investment advice and it does not
        trade. Simulated results are hypothetical.
        <span className="footer-local">
          Runs locally: a personal research tool on your own machine, with no accounts and no hosted service.
        </span>
      </p>
      {/* wraps on phone width (.site-footer nav, Polish v1.0 in globals.css) */}
      <nav aria-label="Footer">
        <Link href="/research/paper">Working paper</Link>
        <Link href="/paper">Paper portfolio</Link>
        <Link href="/methodology">Methodology</Link>
        <Link href="/newsletter#subscribe">Subscribe</Link>
        <Link href="/status">Status</Link>
        <Link href="/legal/disclaimer">Disclaimer</Link>
        <Link href="/legal/terms">Terms</Link>
        <Link href="/legal/privacy">Privacy</Link>
      </nav>
    </footer>
  );
}
