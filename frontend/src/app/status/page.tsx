"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  getAdminToken,
  setAdminToken,
  type AdminStatus,
  type ChainVerify,
  type HealthDetails,
  type HealthHistory,
  type HealthState,
} from "@/lib/api";
import styles from "./status.module.css";

const REFRESH_MS = 60_000;

const LABELS: Record<string, string> = {
  db: "Database",
  ingest: "Filing & news ingest",
  edgar_poller: "EDGAR fast poller",
  halts_poller: "Trading-halts poller",
  journal: "Track-record journal",
  newsletter: "Weekly newsletter",
  alerts: "Discord alerts",
  email: "Email delivery",
  research_job: "Research runs",
};

const STATE_TEXT: Record<HealthState, string> = {
  ok: "Operational",
  degraded: "Degraded",
  down: "Down",
  disabled: "Not configured",
  unknown: "No data yet",
};

function label(name: string) {
  return LABELS[name] ?? name.replace(/_/g, " ");
}

function age(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

function when(iso: string) {
  return new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

function Dot({ state }: { state: HealthState }) {
  return <span className={`${styles.dot} ${styles[state]}`} aria-hidden="true" />;
}

/** Inline SVG bars: one per UTC day, height = overall uptime %, empty outline when there were no samples. */
function UptimeBars({ history }: { history: HealthHistory }) {
  const w = 28;
  const gap = 8;
  const h = 64;
  const width = history.daily.length * (w + gap) - gap;
  const summary =
    history.uptime_pct === null
      ? `No uptime samples in the last ${history.days} days.`
      : `Overall uptime ${history.uptime_pct.toFixed(1)}% over the last ${history.days} days from ${history.samples} samples.`;
  return (
    <figure className={styles.bars}>
      <svg viewBox={`0 0 ${width} ${h + 18}`} width="100%" height={h + 18} role="img" aria-label={summary} preserveAspectRatio="xMinYMid meet">
        {history.daily.map((d, i) => {
          const x = i * (w + gap);
          const pct = d.uptime_pct;
          const barH = pct === null ? 0 : Math.max(2, (pct / 100) * h);
          const tone = pct === null ? styles.barEmpty : pct >= 99 ? styles.barOk : pct >= 90 ? styles.barWarn : styles.barBad;
          const text = `${d.day}: ${pct === null ? "no samples" : `${pct.toFixed(1)}% up (${d.samples} samples)`}`;
          return (
            <g key={d.day}>
              <title>{text}</title>
              <rect x={x} y={0} width={w} height={h} rx={3} className={styles.barTrack} />
              {pct !== null && <rect x={x} y={h - barH} width={w} height={barH} rx={3} className={tone} />}
              <text x={x + w / 2} y={h + 14} textAnchor="middle" className={styles.barLabel}>
                {d.day.slice(5)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="muted small">{summary} Days are UTC. A sample counts as up when the overall status was operational.</figcaption>
    </figure>
  );
}

function ChainResult({ verify, error }: { verify: ChainVerify | null; error: string | null }) {
  if (error) return <p className={styles.bad}>Could not check the track-record seal: {error}</p>;
  if (!verify) return <p className="muted">Checking the track-record seal…</p>;
  if (verify.days === 0) return <p className="muted">Nothing sealed yet. The journal is sealed once a day, shortly after midnight UTC.</p>;
  if (verify.ok)
    return (
      <p>
        <Dot state="ok" /> Verified through <strong>{verify.head_day}</strong>, head <code title={verify.head_hash ?? ""}>{verify.head_hash?.slice(0, 16)}…</code>{" "}
        ({verify.days.toLocaleString("en-US")} sealed days{verify.late_days.length > 0 && `, ${verify.late_days.length} sealed late`}).
      </p>
    );
  const where = verify.first_mismatch?.day ?? verify.broken_link?.day ?? "unknown day";
  return (
    <p className={styles.bad}>
      <Dot state="down" /> Verification failed at {where}
      {verify.broken_link ? `: ${verify.broken_link.reason}` : ": a sealed day no longer matches the journal"}.
    </p>
  );
}

function AdminToken({ admin }: { admin: AdminStatus | null }) {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const t = getAdminToken();
    setValue(t);
    setSaved(!!t);
  }, []);
  return (
    <section className="panel" aria-labelledby="admin-title">
      <h2 id="admin-title">Admin token (this tab only)</h2>
      <p className="muted small">
        {admin === null
          ? "Checking whether this server protects changes…"
          : admin.protected
            ? "This server requires the operator's admin token for changes (watchlist, manual ingest, research runs, test alerts)."
            : admin.mutations_enabled
              ? "This server accepts changes without a token (local deployment)."
              : "Changes are turned off on this server."}{" "}
        The token stays in this browser tab (session storage) and is sent only to this site&apos;s API.
      </p>
      <form
        className={styles.token}
        onSubmit={(e) => {
          e.preventDefault();
          setAdminToken(value);
          setSaved(!!value.trim());
        }}
      >
        <label htmlFor="admin-token">Admin token</label>
        <input
          id="admin-token"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSaved(false);
          }}
        />
        <button type="submit">Save</button>
        <button
          type="button"
          onClick={() => {
            setAdminToken("");
            setValue("");
            setSaved(false);
          }}
        >
          Clear
        </button>
        <span role="status" className="muted small">
          {saved ? "Saved for this tab." : ""}
        </span>
      </form>
    </section>
  );
}

export default function StatusPage() {
  const [details, setDetails] = useState<HealthDetails | null>(null);
  const [history, setHistory] = useState<HealthHistory | null>(null);
  const [verify, setVerify] = useState<ChainVerify | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [admin, setAdmin] = useState<AdminStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .healthDetails()
      .then((d) => {
        setDetails(d);
        setError(null);
      })
      .catch((e) => setError(`Cannot reach the API. ${String(e instanceof Error ? e.message : e)}`));
    api.healthHistory(7).then(setHistory).catch(() => setHistory(null));
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    api
      .journalVerify()
      .then(setVerify)
      .catch((e) => setVerifyError(String(e instanceof Error ? e.message : e)));
    api
      .status()
      .then((s) => setAdmin(s.admin ?? null))
      .catch(() => setAdmin(null));
  }, []);

  const components = details ? Object.entries(details.components) : [];
  const critical = new Set(details?.thresholds.critical ?? []);
  return (
    <main className="page wide">
      <div>
        <h1>System status</h1>
        <p className="muted small">
          Live health of the data pipeline behind Afterfile. Refreshes every minute.
          {details && <> Last checked {when(details.checked_at)}.</>}
        </p>
      </div>

      {error && (
        <div role="alert" className={`panel ${styles.bad}`}>
          <p>{error}</p>
          <button type="button" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {details && (
        <section className={`panel ${styles.overall} ${styles[details.status]}`} aria-live="polite">
          <h2 className={styles.overallTitle}>
            <Dot state={details.status} /> {details.status === "ok" ? "All core systems operational" : details.status === "degraded" ? "Degraded" : "Down"}
          </h2>
          <p className="muted small">
            Core systems: {details.thresholds.critical.map(label).join(", ")}. Ingest counts as stale after{" "}
            {Math.round(details.thresholds.ingest_stale_seconds / 60)} min; the EDGAR poller after {Math.round(details.thresholds.edgar_stale_seconds / 60)} min
            during EDGAR hours ({details.thresholds.edgar_hours_et} ET).
          </p>
        </section>
      )}

      {details && (
        <section className="panel" aria-labelledby="components-title">
          <h2 id="components-title">Components</h2>
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Component</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last activity</th>
                  <th scope="col">Detail</th>
                  <th scope="col">7-day uptime</th>
                </tr>
              </thead>
              <tbody>
                {components.map(([name, c]) => {
                  const up = history?.components[name]?.uptime_pct;
                  return (
                    <tr key={name}>
                      <th scope="row" className={styles.name}>
                        {label(name)}
                        {critical.has(name) && <span className="muted small"> · core</span>}
                      </th>
                      <td>
                        <Dot state={c.status} /> {STATE_TEXT[c.status] ?? c.status}
                      </td>
                      <td>{age(c.age_seconds)}</td>
                      <td className={styles.detail}>{c.detail ?? "—"}</td>
                      <td>{up === undefined || up === null ? "—" : `${up.toFixed(1)}%`}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel" aria-labelledby="uptime-title">
        <h2 id="uptime-title">Uptime, last 7 days</h2>
        {history ? <UptimeBars history={history} /> : <p className="muted">No uptime history yet.</p>}
      </section>

      <section className="panel" aria-labelledby="incidents-title">
        <h2 id="incidents-title">Recent status changes</h2>
        {history && history.incidents.length > 0 ? (
          <ul className={styles.incidents}>
            {history.incidents.slice(0, 15).map((i) => (
              <li key={`${i.at}-${i.component}`}>
                <time dateTime={i.at}>{when(i.at)}</time> · {i.component === "overall" ? "Overall" : label(i.component)}:{" "}
                {STATE_TEXT[i.from as HealthState] ?? i.from} → <strong>{STATE_TEXT[i.to as HealthState] ?? i.to}</strong>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No status changes in the last 7 days.</p>
        )}
      </section>

      <section className="panel" aria-labelledby="seal-title">
        <h2 id="seal-title">Track-record seal</h2>
        <p className="muted small">
          Every UTC day of the forward signal journal is sealed with a SHA-256 hash chained to the previous day, so recorded signals cannot be
          edited after the fact without this check failing. The head hash is also printed in each weekly newsletter.
        </p>
        <ChainResult verify={verify} error={verifyError} />
      </section>

      <AdminToken admin={admin} />
    </main>
  );
}
