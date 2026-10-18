"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ResearchJobKind, type ResearchJobs } from "@/lib/api";
import styles from "./ResearchRunPanel.module.css";

const names = { backtest: "backtest", event_study: "event study" };

export default function ResearchRunPanel({ kind, hasReport, onComplete }: {
  kind: ResearchJobKind;
  hasReport: boolean;
  onComplete: () => void;
}) {
  const [jobs, setJobs] = useState<ResearchJobs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const mounted = useRef(false);
  const busy = useRef(false);
  const checking = useRef(false);
  const request = useRef(0);
  const notified = useRef<string | null>(null);
  const complete = useRef(onComplete);
  useEffect(() => { complete.current = onComplete; }, [onComplete]);

  const refresh = useCallback(async () => {
    if (busy.current || checking.current) return;
    checking.current = true;
    const version = ++request.current;
    try {
      const next = await api.researchJobs();
      if (!mounted.current || request.current !== version) return;
      setJobs(next);
      setError(null);
      const latest = next.latest[kind];
      if (latest?.status === "succeeded" && notified.current !== latest.id) {
        notified.current = latest.id;
        complete.current();
      }
    } catch (e) {
      if (mounted.current && request.current === version) setError(`Cannot check research status. Check that the backend is reachable, then retry. ${String(e instanceof Error ? e.message : e)}`);
    } finally {
      checking.current = false;
    }
  }, [kind]);

  useEffect(() => {
    const version = request;
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 3000);
    return () => { mounted.current = false; ++version.current; window.clearInterval(timer); };
  }, [refresh]);

  async function start() {
    if (busy.current || !jobs || jobs.active || error) return;
    busy.current = true;
    ++request.current;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.startResearch(kind);
      if (!mounted.current) return;
      setJobs((current) => ({ active: job, latest: { backtest: current?.latest.backtest ?? null, event_study: current?.latest.event_study ?? null, [kind]: job } }));
    } catch (e) {
      if (mounted.current) setError(`Could not confirm the run started. Check status before retrying; another run may already be active. ${String(e instanceof Error ? e.message : e)}`);
    } finally {
      busy.current = false;
      if (mounted.current) setSubmitting(false);
    }
  }

  const latest = jobs?.latest[kind];
  const active = jobs?.active;
  return (
    <section className={`panel ${styles.panel}`} aria-label={`Run ${names[kind]}`}>
      <div className={styles.row}>
        <div>
          <h2>{hasReport ? "Update this research" : `Run the ${names[kind]}`}</h2>
          <p className="muted small">Uses the published research settings and cached data. First runs take longer while data downloads. You can leave this page and return while it runs.</p>
        </div>
        <button type="button" className={styles.run} disabled={!jobs || !!active || submitting || !!error} onClick={() => { void start(); }}>
          {submitting ? "Starting…" : active?.kind === kind ? "Running…" : `${hasReport ? "Rerun" : "Run"} ${names[kind]}`}
        </button>
      </div>
      <div role="status" aria-live="polite" aria-atomic="true" className={styles.status}>
        {!jobs && !error && "Checking research status…"}
        {active && <p>{names[active.kind] === "backtest" ? "Backtest" : "Event study"} running. {active.message} {active.kind !== kind && "Wait for this run to finish before starting another."} {hasReport && "The previous report remains available below."}</p>}
        {!active && latest && <p>{latest.status === "succeeded" ? "Completed" : latest.status === "interrupted" ? "Run interrupted" : latest.status === "failed" ? "Run failed" : "Run in progress"}: {latest.message} {(latest.status === "failed" || latest.status === "interrupted") && "You can retry using the run button."}</p>}
        {(active || latest) && <p>Started {new Date((active || latest)!.started_at).toLocaleString()}{!active && latest?.finished_at && ` · Finished ${new Date(latest.finished_at).toLocaleString()}`}</p>}
      </div>
      {error && <div role="alert" className={styles.error}><p>{error}</p><button type="button" disabled={submitting} onClick={() => { void refresh(); }}>Retry status check</button></div>}
    </section>
  );
}
