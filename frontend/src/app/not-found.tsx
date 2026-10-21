import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page">
      <section className="panel">
        <h1>Page not found</h1>
        <p className="muted">There is no Undertow page at this address.</p>
        <p>
          <Link href="/">Home</Link> · <Link href="/signals">Filing signals</Link> · <Link href="/news">Latest news</Link>
        </p>
      </section>
    </main>
  );
}
