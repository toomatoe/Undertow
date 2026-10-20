import Link from "next/link";

import DraftNotice from "@/components/DraftNotice";

export const metadata = { title: "Terms of use · Afterfile" };

export default function TermsPage() {
  return (
    <main className="page prose legal">
      <DraftNotice />
      <h1>Terms of use</h1>
      <p className="muted">Last updated October 19, 2026</p>

      <h2>1. What Afterfile is</h2>
      <p>
        Afterfile is a personal research tool that you run on your own computer. It collects general financial information about public
        SEC filings and market events and shows statistical research about them. It is free, has no accounts and is not offered as a hosted
        service. By running or using it, you agree to these terms and to the <Link href="/legal/disclaimer">Disclaimer</Link>, which is
        part of them.
      </p>

      <h2>2. Not advice</h2>
      <p>
        Afterfile is not a broker-dealer or a registered investment adviser, and it does not provide personalized advice. Its content is
        general and impersonal. Do not rely on it as the basis for any investment decision.
      </p>

      <h2>3. Acceptable use</h2>
      <ul>
        <li>Keep it local. Don&apos;t expose your copy to the public internet or redistribute its research, data or alerts.</li>
        <li>
          Respect the data sources: keep the request rate low, set your own contact details in the SEC user agent, and follow each
          provider&apos;s terms.
        </li>
        <li>Don&apos;t use Afterfile to manipulate markets, spread false information or coordinate trading.</li>
      </ul>

      <h2>4. Third-party data</h2>
      <p>
        Content comes from third parties (SEC, FINRA, Nasdaq, news publishers) under their own terms. Headlines link to the original
        source; Afterfile does not republish full articles. The price history used for research comes from Yahoo Finance for personal use
        only: it is cached on your machine and must not be shared or served to others. Third-party data is provided as-is, and its
        providers make no warranties to you.
      </p>

      <h2>5. Optional features</h2>
      <p>
        Email delivery, Discord alerts, AI summaries and the Alpaca news feed are all off by default. They turn on only when you add your
        own settings to your local configuration, and they then run under the terms of the service you connect.
      </p>

      <h2>6. No warranty; limitation of liability</h2>
      <p>
        Afterfile is provided &quot;as is&quot;, without warranties of accuracy, timeliness, availability or fitness for a purpose. Alerts can be
        late, missing or wrong. To the maximum extent the law allows, its authors are not liable for any trading losses or for indirect,
        incidental or consequential damages arising from your use of it.
      </p>

      <h2>7. Changes</h2>
      <p>These terms may change with new versions of Afterfile. The date at the top shows the latest update.</p>

      <h2>8. Contact</h2>
      <p>Questions about these terms: use the contact details on the project repository.</p>
    </main>
  );
}
