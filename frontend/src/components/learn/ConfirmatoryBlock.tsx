// The pre-registered out-of-sample verdicts (event_study_oos.json `confirmatory`). No hooks: used by the
// server-rendered clustered-errors lesson and by the client Edge Lab page.

import type { EventStudy } from "@/lib/api";
import { pctOr } from "@/lib/format";

import styles from "./learn.module.css";
import { fmtT, LiveTag, RepoPath, VerdictBadge } from "./parts";

const CHECK_LABELS: Record<string, string> = {
  n: "enough events",
  companies: "enough companies",
  t_vs_zero: "clustered |t| vs zero",
  t_vs_baseline: "clustered |t| vs ordinary days",
  mean_registered_way: "mean in the registered direction",
  excess_registered_way: "excess in the registered direction",
  mean_net_positive: "positive after costs",
};

export default function ConfirmatoryBlock({ study, heading = "h2" }: { study: EventStudy; heading?: "h2" | "h3" }) {
  const rows = study.confirmatory ?? [];
  const ct = study.confirmatory_testing;
  const H = heading;
  if (!rows.length) return null;
  return (
    <section className="panel" aria-label="Pre-registered confirmatory tests">
      <H>Confirmatory tests (pre-registered)</H>
      <p className="small">
        Three hypotheses fixed on {study.preregistered_on ?? "the registration date"} in{" "}
        {study.preregistration ? <RepoPath path={study.preregistration} /> : "the pre-registration file"}, before any out-of-sample data
        was seen. Each uses the firm-clustered t against a Bonferroni family of {ct?.family_size ?? 3} (|t| ≥ {ct?.t_critical ?? "—"}), at
        least {ct?.min_n ?? 20} events and {ct?.min_companies ?? 15} companies. Everything else in this study is exploratory.
      </p>
      <div className={styles.tableScroll}>
        <table className="data">
          <thead>
            <tr>
              <th>Hypothesis</th>
              <th>Cells</th>
              <th>n</th>
              <th>Companies</th>
              <th>Mean drift</th>
              <th>Ordinary days</th>
              <th>Excess</th>
              <th>Clustered t</th>
              <th>t vs ordinary</th>
              <th>Net</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.hypothesis}>
                <td>
                  <strong>{r.hypothesis}</strong> {r.label}
                </td>
                <td className="small">{r.cells.join(", ")}</td>
                <td>{r.n}</td>
                <td>{r.companies}</td>
                <td>{pctOr(r.mean_abnormal)}</td>
                <td>{pctOr(r.baseline_mean)}</td>
                <td>{pctOr(r.excess_vs_baseline)}</td>
                <td>{fmtT(r.t_clustered)}</td>
                <td>{fmtT(r.t_vs_baseline_clustered)}</td>
                <td>{pctOr(r.mean_net)}</td>
                <td>
                  <VerdictBadge verdict={r.verdict} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="small">
        {rows.map((r) => {
          const failed = Object.entries(r.checks)
            .filter(([, ok]) => !ok)
            .map(([k]) => CHECK_LABELS[k] ?? k);
          return (
            <li key={r.hypothesis}>
              <strong>{r.hypothesis}</strong>: {failed.length ? `failed: ${failed.join(", ")}` : "every pre-registered check passed"}.
            </li>
          );
        })}
      </ul>
      <p className="muted small">
        <LiveTag kind="historical, hypothetical" date={study.generated_at} what="study generated" /> Window {study.config.window[0]} to{" "}
        {study.config.window[1]}. Net figures assume fixed costs and borrow and are hypothetical. A replication is evidence about a past
        pattern, not a forecast.
      </p>
    </section>
  );
}
