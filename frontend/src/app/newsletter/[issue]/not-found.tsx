import Link from "next/link";

export default function IssueNotFound() {
  return (
    <main className="page">
      <Link href="/newsletter" className="back">
        ← Newsletter archive
      </Link>
      <section className="panel">
        <h1>No such newsletter issue</h1>
        <p className="muted">
          Issues are named by ISO week (for example 2026-W41) and are built automatically on Monday for the week that just ended. This one is not in the
          archive.
        </p>
        <p>
          <Link href="/newsletter">Browse the archive</Link>
        </p>
      </section>
    </main>
  );
}
