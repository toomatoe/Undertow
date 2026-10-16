import Link from "next/link";

import DraftNotice from "@/components/DraftNotice";

export const metadata = { title: "Terms of use · QuantDesk" };

export default function TermsPage() {
  return (
    <main className="page prose legal">
      <DraftNotice />
      <h1>Terms of use</h1>
      <p className="muted">Last updated October 16, 2026</p>

      <h2>1. What QuantDesk is</h2>
      <p>
        QuantDesk is a publication of general financial information and research about public SEC filings and market events. By using the
        site, the API or our alerts, you agree to these terms and to the <Link href="/legal/disclaimer">Disclaimer</Link>, which is part of
        them.
      </p>

      <h2>2. Not advice</h2>
      <p>
        QuantDesk is not a broker-dealer or a registered investment adviser, and it does not provide personalized advice. Content is
        impersonal and offered to all users on the same terms. Do not rely on it as the basis for any investment decision.
      </p>

      <h2>3. Acceptable use</h2>
      <ul>
        <li>Don&apos;t resell, redistribute or republish our alerts, research or data feeds without written permission.</li>
        <li>Don&apos;t scrape the site or API faster than normal use, try to break security, or interfere with service for others.</li>
        <li>Don&apos;t use QuantDesk to manipulate markets, spread false information or coordinate trading.</li>
      </ul>

      <h2>4. Third-party data</h2>
      <p>
        Some content comes from third parties (SEC, FINRA, Nasdaq, news publishers) under their own terms. Headlines link to the original
        source; we do not republish full articles. Third-party data is provided as-is, and its providers make no warranties to you.
      </p>

      <h2>5. Accounts and subscriptions</h2>
      <p>
        If paid plans are offered, pricing, billing periods and cancellation terms will be shown before purchase. You can cancel any time;
        access continues until the end of the paid period. We may change plans with notice.
      </p>

      <h2>6. No warranty; limitation of liability</h2>
      <p>
        The service is provided &quot;as is&quot;, without warranties of accuracy, timeliness, availability or fitness for a purpose. Alerts can be
        late, missing or wrong. To the maximum extent the law allows, QuantDesk is not liable for any trading losses or for indirect,
        incidental or consequential damages arising from your use of the service. Our total liability is limited to the amount you paid us in
        the 12 months before the claim.
      </p>

      <h2>7. Changes</h2>
      <p>We may update these terms. Material changes will be announced on the site. Continued use after a change means you accept it.</p>

      <h2>8. Contact</h2>
      <p>Questions about these terms: use the contact details on the repository or site homepage.</p>
    </main>
  );
}
