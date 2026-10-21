import Link from "next/link";

export default function TickerNotFound() {
  return (
    <main className="page">
      <Link href="/news" className="back">
        ← News
      </Link>
      <section className="panel ticker-missing">
        <h1>No data for this ticker yet</h1>
        <p className="muted">
          Undertow has no filings or news on record for this symbol. Pages appear once a company files with the SEC or is mentioned in a
          tracked source.
        </p>
        <p>
          <Link href="/signals">Browse filing signals</Link> · <Link href="/news">Latest news</Link>
        </p>
      </section>
    </main>
  );
}
