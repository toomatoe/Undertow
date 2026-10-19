"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import styles from "./SubscribeForm.module.css";

type State = { kind: "idle" } | { kind: "sending" } | { kind: "done"; message: string } | { kind: "error"; message: string };

/**
 * Email signup for the weekly Filing Radar (and optional daily digest). Double opt-in: the backend sends a
 * confirmation link and always answers with the same generic message, so this form never reveals whether an
 * address is already subscribed. Client island inside the server-rendered /newsletter page.
 */
export default function SubscribeForm() {
  const [email, setEmail] = useState("");
  const [daily, setDaily] = useState(false);
  const [state, setState] = useState<State>({ kind: "idle" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (state.kind === "sending") return;
    setState({ kind: "sending" });
    try {
      const res = await api.subscribe(email.trim(), daily);
      setState({ kind: "done", message: res.message });
    } catch (err) {
      let message = "Could not reach the server. Please try again later.";
      if (err instanceof ApiError) {
        if (err.status === 503) message = "Email delivery isn't set up on this server yet.";
        else if (err.status === 422) message = "Enter a valid email address.";
        else if (err.status === 429) message = err.message.replace(/^429 /, "");
        else message = `Could not subscribe right now (${err.status}). Please try again later.`;
      }
      setState({ kind: "error", message });
    }
  }

  return (
    <section id="subscribe" className={`panel ${styles.box}`} aria-labelledby="subscribe-title">
      <h2 id="subscribe-title">Get the Radar by email</h2>
      <p className="muted small">
        Free, weekly, impersonal facts and historical statistics only. You confirm by email first; every message has a one-click
        unsubscribe link.
      </p>
      {state.kind === "done" ? (
        <p role="status" className={styles.ok}>
          {state.message}
        </p>
      ) : (
        <form className={styles.form} onSubmit={(e) => void submit(e)}>
          <label htmlFor="subscribe-email" className={styles.label}>
            Email address
          </label>
          <div className={styles.row}>
            <input
              id="subscribe-email"
              type="email"
              required
              autoComplete="email"
              inputMode="email"
              maxLength={254}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={state.kind === "error"}
              aria-describedby={state.kind === "error" ? "subscribe-error" : undefined}
              className={styles.input}
            />
            <button type="submit" className={styles.button} disabled={state.kind === "sending" || !email.trim()}>
              {state.kind === "sending" ? "Sending…" : "Subscribe"}
            </button>
          </div>
          <label className={styles.check}>
            <input type="checkbox" checked={daily} onChange={(e) => setDaily(e.target.checked)} />
            Also send the daily digest (the previous day&apos;s serious small-cap filings, each morning)
          </label>
          {state.kind === "error" && (
            <p id="subscribe-error" role="alert" className={styles.error}>
              {state.message}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
