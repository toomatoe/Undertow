import DraftNotice from "@/components/DraftNotice";

export const metadata = { title: "Privacy · QuantDesk" };

export default function PrivacyPage() {
  return (
    <main className="page prose legal">
      <DraftNotice />
      <h1>Privacy</h1>
      <p className="muted">Last updated October 16, 2026</p>

      <h2>What we collect today</h2>
      <ul>
        <li>
          <strong>No accounts yet.</strong> Watchlists are stored on the QuantDesk server you run, not tied to any identity.
        </li>
        <li>
          <strong>Server logs:</strong> standard request logs (IP address, time, page) kept for security and debugging, rotated regularly.
        </li>
        <li>
          <strong>Alert delivery:</strong> if you configure a Discord webhook, its URL is kept in the server&apos;s environment
          configuration only.
        </li>
      </ul>

      <h2>What we don&apos;t do</h2>
      <ul>
        <li>No selling or sharing of personal data.</li>
        <li>No advertising trackers or third-party analytics.</li>
        <li>No access to brokerage accounts, positions or trades.</li>
      </ul>

      <h2>When accounts and payments are added</h2>
      <p>
        We will collect only what is needed: an email address for login and alerts, and billing handled by a payment processor (we will not
        store card numbers). This page will be updated before that launches, with retention periods and how to delete your data.
      </p>

      <h2>Outbound requests</h2>
      <p>
        The server fetches public data from SEC EDGAR, FINRA, Nasdaq Trader, news RSS feeds and, for research, Yahoo Finance. These
        requests carry a generic user agent and no information about you.
      </p>
    </main>
  );
}
