"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ResearchRequestError, type ResearchJobKind, type ResearchJobs } from "@/lib/api";
import styles from "./ResearchRunPanel.module.css";

const names = { backtest: "backtest", event_study: "event study" };
// Admin token for protected deployments; kept for this browser tab only.
const TOKEN_KEY = "quantdesk.researchAdminToken";

export default function ResearchRunPanel({ kind, hasReport, onComplete }: {
  kind: ResearchJobKind;
  hasReport: boolean;
  onComplete: () => void;
}) {
  const [jobs, setJobs] = useState<ResearchJobs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [token, setToken] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
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

  useEffect(() => {
    try { setToken(window.sessionStorage.getItem(TOKEN_KEY) ?? ""); } catch { /* storage unavailable */ }
  }, []);

  function updateToken(value: string) {
    setToken(value);
    setAuthError(null);
    try { window.sessionStorage.setItem(TOKEN_KEY, value); } catch { /* storage unavailable */ }
  }

  async function start() {
    if (busy.current || !jobs || jobs.active || !jobs.enabled || error) return;
    if (jobs.requires_token && !token.trim()) { setAuthError("Enter the admin token to start a run."); return; }
    busy.current = true;
    ++request.current;
    setSubmitting(true);
    setError(null);
    setAuthError(null);
    try {
      const job = await api.startResearch(kind, jobs.requires_token ? token.trim() : undefined);
      if (!mounted.current) return;
      setJobs((current) => current && ({ ...current, active: job, latest: { ...current.latest, [kind]: job } }));
    } catch (e) {
      if (!mounted.current) return;
      const detail = String(e instanceof Error ? e.message : e);
      if (e instanceof ResearchRequestError && e.status === 401) setAuthError("The admin token was not accepted. Check it and try again.");
      else if (e instanceof ResearchRequestError && e.status === 403) setError(`Research runs are turned off on this server. ${detail}`);
      else setError(`Could not confirm the run started. Check status before retrying; another run may already be active. ${detail}`);
    } finally {
      busy.current = false;
      if (mounted.current) setSubmitting(false);
    }
  }

  const latest = jobs?.latest[kind];
  const active = jobs?.active;
  const tokenId = `research-token-${kind}`;
  return (
    <section className={`panel ${styles.panel}`} aria-label={`Run ${names[kind]}`}>
      <div className={styles.row}>
        <div>
          <h2>{hasReport ? "Update this research" : `Run the ${names[kind]}`}</h2>
          <p className="muted small">Uses the published research settings and cached data. First runs take longer while data downloads. You can leave this page and return while it runs.</p>
        </div>
        {(!jobs || jobs.enabled) && (
          <button type="button" className={styles.run} disabled={!jobs || !!active || submitting || !!error} onClick={() => { void start(); }}>
            {submitting ? "Starting…" : active?.kind === kind ? "Running…" : `${hasReport ? "Rerun" : "Run"} ${names[kind]}`}
          </button>
        )}
      </div>
      {jobs && !jobs.enabled && <p className={`muted small ${styles.note}`}>Runs from this page are turned off on this server. The operator can run research from the command line, or set RESEARCH_ADMIN_TOKEN to allow authorized runs here.</p>}
      {jobs?.enabled && jobs.requires_token && (
        <div className={styles.token}>
          <label htmlFor={tokenId}>Admin token</label>
          <input id={tokenId} type="password" autoComplete="off" spellCheck={false} value={token} disabled={!!active || submitting}
            aria-invalid={!!authError} aria-describedby={authError ? `${tokenId}-error` : undefined}
            onChange={(e) => updateToken(e.target.value)} />
          {authError && <p id={`${tokenId}-error`} role="alert" className={styles.error}>{authError}</p>}
        </div>
      )}
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
