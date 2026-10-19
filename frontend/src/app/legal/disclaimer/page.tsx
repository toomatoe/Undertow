import Link from "next/link";

import DraftNotice from "@/components/DraftNotice";

export const metadata = { title: "Disclaimer · QuantDesk" };

export default function DisclaimerPage() {
  return (
    <main className="page prose legal">
      <DraftNotice />
      <h1>Disclaimer</h1>
      <p className="muted">Last updated October 19, 2026</p>

      <h2>Research and information only</h2>
      <p>
        QuantDesk is a personal research tool that runs on your own computer. It shows general, impersonal information about public SEC
        filings, trading halts and market data, along with statistical research about how stocks have historically behaved after those
        events. Nothing in QuantDesk, its alerts, newsletters or emails is investment, legal, tax or accounting advice, or a recommendation
        to buy, sell or hold any security.
      </p>
      <p>
        QuantDesk does not know your financial situation, objectives or risk tolerance, and nothing it shows is tailored to you. Watchlists
        and filters only narrow down the same public information. QuantDesk does not manage money, take custody of funds, execute trades or
        connect to brokerage accounts.
      </p>

      <h2>Hypothetical and simulated performance</h2>
      <p>
        The <Link href="/lab">Edge Lab</Link>, the <Link href="/backtest">Backtest</Link> and the{" "}
        <Link href="/track-record">Track record</Link> show <strong>hypothetical</strong> results. No real trades were made. Hypothetical
        results have inherent limitations:
      </p>
      <ul>
        <li>They are prepared with the benefit of hindsight. A rule that looks good on past data may simply have fit noise.</li>
        <li>
          They cannot fully model real-world frictions: bid-ask spreads, slippage, short-borrow availability and fees, recalls, halts, margin
          calls and taxes. We model some of these with stated assumptions; actual costs can be much higher.
        </li>
        <li>They exclude companies whose price history is unavailable, which is usually companies that later delisted.</li>
        <li>
          Past performance, real or simulated, does not guarantee future results. Small-cap and nano-cap stocks are especially volatile,
          illiquid and risky. You can lose all of the money you invest, and short selling can lose more than you invest.
        </li>
      </ul>
      <p>
        QuantDesk&apos;s own backtest of the strongest signal it found concluded it was <strong>not tradable</strong> after realistic costs.
        Losing results and drawdowns are shown alongside everything else, and simulated results are never presented as real.
      </p>

      <h2>Data accuracy</h2>
      <p>
        Data comes from public sources: SEC EDGAR, FINRA, Nasdaq Trader and news feeds. Research price history comes from Yahoo Finance for
        personal use only and is never redistributed. Data may be delayed, incomplete or wrong. Automated classification (signal types,
        company size, ticker matching, AI summaries) can misread filings. Always read the original filing, which every alert links to,
        before acting on anything.
      </p>

      <h2>No sponsors, no conflicts</h2>
      <ul>
        <li>QuantDesk is free and has no paying customers, advertisers or sponsors.</li>
        <li>No company pays to be covered, promoted or left out.</li>
      </ul>

      <h2>Your responsibility</h2>
      <p>
        You are solely responsible for your investment decisions. Consider talking to a licensed financial professional before making any
        investment. See also the <Link href="/legal/terms">Terms of use</Link> and <Link href="/methodology">Methodology</Link>.
      </p>
    </main>
  );
}
