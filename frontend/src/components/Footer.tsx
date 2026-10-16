import Link from "next/link";

export default function Footer() {
  return (
    <footer className="site-footer">
      <p>
        QuantDesk publishes general information about public filings and historical statistics. It is not investment advice. Simulated
        results are hypothetical.
      </p>
      <nav>
        <Link href="/methodology">Methodology</Link>
        <Link href="/legal/disclaimer">Disclaimer</Link>
        <Link href="/legal/terms">Terms</Link>
        <Link href="/legal/privacy">Privacy</Link>
      </nav>
    </footer>
  );
}
