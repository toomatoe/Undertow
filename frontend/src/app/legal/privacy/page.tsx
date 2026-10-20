import DraftNotice from "@/components/DraftNotice";

export const metadata = { title: "Privacy · Afterfile" };

export default function PrivacyPage() {
  return (
    <main className="page prose legal">
      <DraftNotice />
      <h1>Privacy</h1>
      <p className="muted">Last updated October 19, 2026</p>

      <p>
        Afterfile runs on your own computer. Everything it stores stays in your local database and data folder; nobody else operates a
        server for it, and there are no accounts.
      </p>

      <h2>What is stored, and where</h2>
      <ul>
        <li>
          <strong>No accounts.</strong> Watchlists are stored in your local Afterfile database, not tied to any identity.
        </li>
        <li>
          <strong>Local logs:</strong> the API and web containers write standard request logs (address, time, page) on your machine only.
        </li>
        <li>
          <strong>Alert delivery (optional, off by default):</strong> if you configure a Discord webhook, its URL is kept only in your local
          environment configuration.
        </li>
        <li>
          <strong>Email (optional, off by default):</strong> email delivery stays off unless you configure your own mail server. If you turn
          it on, subscriber addresses are stored in your local database, only after double opt-in, and every email has an unsubscribe link.
        </li>
      </ul>

      <h2>What Afterfile doesn&apos;t do</h2>
      <ul>
        <li>No selling or sharing of personal data.</li>
        <li>No advertising trackers or third-party analytics.</li>
        <li>No payments and no card numbers: Afterfile is free.</li>
        <li>No access to brokerage accounts, positions or trades.</li>
      </ul>

      <h2>Deleting your data</h2>
      <p>
        All data lives in your local Docker volumes and data folder. Removing them (for example with <code>docker compose down -v</code>)
        deletes everything Afterfile stored.
      </p>

      <h2>Outbound requests</h2>
      <p>
        Your local Afterfile fetches public data from SEC EDGAR, FINRA, Nasdaq Trader, news RSS feeds and, for research, Yahoo Finance.
        SEC requests carry the user agent you configure (SEC asks for a contact address); no other information about you is sent. Optional
        integrations you turn on (Alpaca, Anthropic, Discord, your mail server) receive only what they need to work.
      </p>
    </main>
  );
}
