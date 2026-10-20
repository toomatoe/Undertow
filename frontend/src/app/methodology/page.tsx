import Link from "next/link";

export const metadata = { title: "Methodology · Undertow" };

export default function MethodologyPage() {
  return (
    <main className="page prose legal">
      <h1>Methodology</h1>
      <p className="muted">
        How every number on Undertow is produced, what it assumes, and where it can be wrong. If you can&apos;t see how a number was
        made, don&apos;t trust it, including ours.
      </p>

      <h2>Data sources</h2>
      <ul>
        <li>
          <strong>SEC EDGAR</strong>: the live filing feeds (8-K, 424B4/5, S-1, S-3, Schedule 13D), company filing histories, and XBRL
          financial data. Public domain.
        </li>
        <li>
          <strong>SEC public float</strong> (10-K cover page): used to size companies. It is the market value of shares held by outsiders,
          measured at the end of Q2, which is a conservative proxy for market cap.
        </li>
        <li><strong>FINRA</strong>: short interest, published twice a month.</li>
        <li><strong>Nasdaq Trader</strong>: trading halts and resumptions, checked every 30 seconds.</li>
        <li><strong>IBKR shortable-stocks file</strong>: borrow fee and availability, archived daily since October 16, 2026.</li>
        <li>
          <strong>Prices for research</strong>: Yahoo Finance daily closes, adjusted for splits. This is a personal-use research source; a
          licensed feed is required before prices are shown publicly.
        </li>
        <li><strong>News</strong>: public RSS feeds. Headlines link to the publisher; full articles are never republished.</li>
      </ul>
      <p>
        <strong>Research prices and their limits.</strong> The prices behind the Edge Lab, the backtest and the working paper come from
        Yahoo Finance and are used for personal, local research only. They are cached on the machine that runs the studies and are never
        redistributed or served by the API; only aggregate statistics (averages, t-statistics, counts) are shown. Because of this, the app is
        not to be deployed publicly with Yahoo prices: a public deployment needs a licensed price feed first.
      </p>
      <p>
        Every design choice, result table and limitation of the studies is written up in one document:{" "}
        <Link href="/research/paper">Read the working paper</Link>.
      </p>

      <h2>Signals</h2>
      <p>
        A signal is a filing type with a known, pre-specified meaning: for example 8-K item 4.01 (auditor change), item 3.01 (delisting
        notice), item 3.02 (unregistered share sale), or a 424B prospectus (priced offering). Each has an expected direction (▼, ▲ or ◆
        &quot;depends on content&quot;) and a severity from 1 to 3. The full list is the signal filter on the{" "}
        <Link href="/signals">Signals</Link> page. Signals come only from the filing&apos;s form and item numbers, never from price action.
      </p>

      <h2>Company size</h2>
      <p>Buckets by public float: nano under $50M, micro $50–300M, small $300M–2B, mid $2–10B, large over $10B.</p>

      <h2>Edge Lab (event study)</h2>
      <ul>
        <li>A random sample of 750 operating companies (no SPACs or funds), sized at the start of the study window.</li>
        <li>
          Day 0 is the first close after EDGAR&apos;s acceptance timestamp (the next day if accepted after 3:30 pm ET). Drift is measured
          from the day-0 close.
        </li>
        <li>
          Returns are measured against IWM (SPY for large caps) and compared with the same stocks on ordinary days, so a signal must beat
          small caps&apos; general drift.
        </li>
        <li>Outliers are winsorized at the 1st and 99th percentiles.</li>
        <li>
          A result counts only if it survives a Bonferroni correction across every signal × size × horizon tested, points the expected way,
          and clears estimated costs.
        </li>
        <li>The design was fixed before results were seen. Changing it afterwards would be data snooping.</li>
      </ul>

      <h2>Backtest</h2>
      <ul>
        <li>Covers every priced offering by a sub-$50M-float company in two periods: 2020–23 (out-of-sample) and 2023–26 (discovery).</li>
        <li>
          Simulated day by day:
          <ul>
            <li>Entry one close after day 0 (Rule 201 often blocks shorting into the first drop).</li>
            <li>A $1 floor on the price that actually traded, and a liquidity floor; position size is capped by volume.</li>
            <li>3% round-trip costs and 75%/yr borrow; 30% of names randomly unborrowable; 2%/day recalls.</li>
            <li>A squeeze stop with slippage, no credit for delistings, and an IWM hedge.</li>
          </ul>
        </li>
        <li>
          Every simulation is logged. The Deflated Sharpe Ratio accounts for how many strategy variants were tried. 13 readiness gates
          decide the verdict, and nothing can say &quot;ready for real money&quot; while operational gates (borrow data, paper trading, risk
          controls) are open.
        </li>
        <li>
          Result: <Link href="/backtest">not tradable as specified</Link>. The drift is real, but costs, borrow and squeezes consume it.
        </li>
      </ul>

      <h2>Track record</h2>
      <p>
        Every signal is recorded when it is first seen, with a timestamp, and is never edited. It is priced at the same close the backtest
        would trade and compared with IWM after 1, 5 and 20 trading days. Results appear next to what the Edge Lab expected, so you can see
        whether historical patterns keep working. Entries whose stock stops trading are marked, not deleted.
      </p>

      <h2>Cash runway and dilution</h2>
      <p>
        Runway is cash plus short-term investments, divided by trailing-12-month operating cash burn, both from XBRL as reported, as of the
        balance-sheet date. Any raise after that date extends it. Share-count change compares cover-page share counts about a year apart.
        It is arithmetic on reported numbers, not a forecast.
      </p>

      <h2>Alerts</h2>
      <p>
        Alerts go out for severity 2+ signals on companies under $2B float or on your watchlist, plus news and regulatory halts. Each alert
        shows its detection latency: the time from SEC acceptance to our detection. Alerts state facts and historical statistics; they never
        say buy or sell.
      </p>

      <h2>Known limitations</h2>
      <ul>
        <li>Survivorship: delisted companies are often missing price history, so historical results lean optimistic.</li>
        <li>Borrow costs at the moment of an offering are unknown historically; we archive real data going forward.</li>
        <li>XBRL tagging varies by company; when data is missing we show it as missing instead of guessing.</li>
        <li>AI summaries, where enabled, can misread filings. The original filing is always linked.</li>
      </ul>
      <p>
        See the <Link href="/legal/disclaimer">Disclaimer</Link>. The full code and research notes are in the project repository.
      </p>
    </main>
  );
}
