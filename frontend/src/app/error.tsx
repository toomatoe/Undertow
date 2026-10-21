"use client";

import Link from "next/link";

/** Friendly boundary for render errors (e.g. the API is restarting or rate limited) instead of Next's blank screen. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const busy = /429|Too Many Requests/i.test(error.message);
  return (
    <main className="page">
      <section className="panel">
        <h1>{busy ? "The API is busy" : "This page could not load"}</h1>
        <p className="muted">
          {busy
            ? "Too many requests reached the local API at once. Wait a few seconds and try again."
            : "The local API may be starting up or restarting. Try again in a moment."}
        </p>
        <p>
          <button type="button" className="btn" onClick={reset}>
            Try again
          </button>{" "}
          <Link href="/">Home</Link>
        </p>
      </section>
    </main>
  );
}
