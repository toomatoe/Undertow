"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ResearchRunPanel from "@/components/ResearchRunPanel";

import { api, type EventStudy, type StudyResult } from "@/lib/api";
import { pct, pctAbs, SIZE_LABELS } from "@/lib/format";

const BUCKET_ORDER = ["nano", "micro", "small", "mid", "large"];

function DivergingChart({
  results,
  bucket,
  maxAbs,
  cost,
  borrowApr,
}: {
  results: StudyResult[];
  bucket: string;
  maxAbs: number;
  cost: number;
  borrowApr: number;
}) {
  const [hover, setHover] = useState<StudyResult | null>(null);
  const rows = [...results].sort((a, b) => b.mean_net - a.mean_net);
  return (
    <figure className="facet">
      <figcaption>
        <strong>{SIZE_LABELS[bucket] ?? bucket}</strong>
        <span className="muted small">
          {" "}
          · {pctAbs(cost)} round trip{borrowApr > 0 && `, shorts also pay ~${pctAbs(borrowApr, 0)}/yr borrow`}
        </span>
      </figcaption>
      <div className="div-chart" onMouseLeave={() => setHover(null)}>
        {rows.map((r) => {
          const w = (Math.abs(r.mean_net) / maxAbs) * 50;
          const pos = r.mean_net >= 0;
          return (
            <div
              key={r.signal}
              className={`div-row ${hover?.signal === r.signal ? "hover" : ""}`}
              onMouseEnter={() => setHover(r)}
              onFocus={() => setHover(r)}
              tabIndex={0}
            >
              <span className={`div-label ${r.significant ? "sig" : ""}`} title={r.label}>
                {r.significant && "✓ "}
                {r.label}
              </span>
              <span className="div-track">
                <span className="div-zero" />
                <span
                  className={`div-bar ${pos ? "pos" : "neg"}`}
                  style={pos ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
                />
              </span>
              <span className="div-value">{pct(r.mean_net)}</span>
            </div>
          );
        })}
        {hover && (
          <div className="tooltip" role="status">
            <strong>{hover.label}</strong>
            <span>
              Trade: {hover.direction === "-" ? "short" : "long"} at day-0 close, hold {hover.horizon_days}d
            </span>
            <span>Gross drift vs index: {pct(hover.mean_abnormal, 2)} (median {pct(hover.median_abnormal, 2)})</span>
            <span>
              Same stocks on ordinary days: {hover.baseline_mean === null ? "—" : pct(hover.baseline_mean, 2)} → excess{" "}
              {hover.excess_vs_baseline === null ? "—" : pct(hover.excess_vs_baseline, 2)} (t = {hover.t_vs_baseline ?? "—"})
            </span>
            <span>
              Net of {pctAbs(hover.cost)} costs{hover.borrow > 0 ? ` incl. ${pctAbs(hover.borrow)} borrow` : ""}: {pct(hover.mean_net, 2)}
            </span>
            <span>
              n = {hover.n} events · {hover.companies} companies · t = {hover.t_stat}
            </span>
            <span>Day-0 reaction: {pct(hover.mean_reaction, 2)}</span>
            <span>{hover.significant ? "Survives multiple-testing correction" : "Not significant after correction"}</span>
          </div>
        )}
      </div>
    </figure>
  );
}

export default function LabPage() {
  const [study, setStudy] = useState<EventStudy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState(20);

  const loadVersion = useRef(0);
  const reload = useCallback(() => {
    const version = ++loadVersion.current;
    api.eventStudy().then((next) => {
      if (version !== loadVersion.current) return;
      setStudy(next); setError(null);
    }).catch((e) => { if (version === loadVersion.current) setError(String(e.message ?? e)); });
  }, []);
  useEffect(() => {
    const version = loadVersion;
    reload();
    return () => { ++version.current; };
  }, [reload]);

  const byBucket = useMemo(() => {
    const m = new Map<string, StudyResult[]>();
    for (const r of study?.results ?? []) {
      if (r.horizon_days !== horizon) continue;
      m.set(r.bucket, [...(m.get(r.bucket) ?? []), r]);
    }
    return BUCKET_ORDER.filter((b) => m.has(b)).map((b) => [b, m.get(b)!] as const);
  }, [study, horizon]);

  const maxAbs = useMemo(
    () => Math.max(0.01, ...byBucket.flatMap(([, rs]) => rs.map((r) => Math.abs(r.mean_net)))),
    [byBucket],
  );

  if (!study) {
    return (
      <main className="page">
        <h1>Edge Lab</h1>
        <ResearchRunPanel kind="event_study" hasReport={false} onComplete={reload} />
        {error?.startsWith("404") ? <p>No study yet. Start a run above to generate the results.</p> : error ? <div role="alert"><p className="error">Couldn&apos;t load the study. Check the backend connection. {error}</p><button onClick={reload}>Retry loading study</button></div> : <p role="status">Loading study…</p>}
      </main>
    );
  }

  const significant = study.results.filter((r) => r.significant);
  const totalCompanies = Object.values(study.coverage).reduce((s, c) => s + (c.companies ?? 0), 0);
  const priced = Object.values(study.coverage).reduce((s, c) => s + (c.with_prices ?? 0), 0);

  return (
    <main className="page wide">
      <h1>Edge Lab</h1>
      <ResearchRunPanel kind="event_study" hasReport onComplete={reload} />
      {error && <div role="alert"><p className="error">Couldn&apos;t refresh the study; showing the previous result. {error}</p><button onClick={reload}>Retry loading study</button></div>}
      <p className="muted lede">
        Do SEC filing events predict how a stock moves next, after trading costs? An event study over{" "}
        {study.config.window[0]} to {study.config.window[1]}, with companies sorted by size at the start of the
        window. Run {new Date(study.generated_at).toLocaleDateString()}.
      </p>

      <div className="tiles">
        <div className="tile">
          <span className="muted small">Events measured</span>
          <strong>{study.measured_events.toLocaleString()}</strong>
        </div>
        <div className="tile">
          <span className="muted small">Companies with prices</span>
          <strong>
            {priced} <span className="muted small">of {totalCompanies}</span>
          </strong>
        </div>
        <div className="tile">
          <span className="muted small">Tests run</span>
          <strong>{study.testing.n_tests}</strong>
        </div>
        <div className="tile">
          <span className="muted small">Survive correction &amp; costs</span>
          <strong>{significant.length}</strong>
        </div>
      </div>

      <section className="panel">
        <h2>What survived</h2>
        {significant.length === 0 ? (
          <p>
            Nothing. No signal produced drift that was both statistically significant after correcting for{" "}
            {study.testing.n_tests} tests (|t| ≥ {study.testing.t_critical}), different from the same stocks on ordinary days, and profitable after assumed costs.
            That is a useful answer: filing events alone are not a trading edge in this sample.
          </p>
        ) : (
          <ul className="findings">
            {significant.map((r) => (
              <li key={`${r.signal}-${r.bucket}-${r.horizon_days}`}>
                <strong>{r.label}</strong> in {r.bucket} caps: {pct(r.mean_abnormal)} vs index over {r.horizon_days}{" "}
                trading days (n={r.n}, t={r.t_stat}). Ordinary days for the same stocks: {r.baseline_mean === null ? "—" : pct(r.baseline_mean)}, so the filing adds{" "}
                {r.excess_vs_baseline === null ? "—" : pct(r.excess_vs_baseline)} (t={r.t_vs_baseline}). {pct(r.mean_net)} after {pctAbs(r.cost)} costs and borrow if{" "}
                {r.direction === "-" ? "shorted" : "bought"} at the day-0 close.
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">
          Significance uses a Bonferroni correction across every signal × size × horizon tested (|t| ≥{" "}
          {study.testing.t_critical}). The drift must also differ from the same stocks on ordinary days by the same margin, point the expected way, and clear costs plus estimated borrow for shorts. Results with |t| ≥
          1.96 that fail this are listed in the table as nominal only.
        </p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Net drift after costs, by signal and size</h2>
          <div className="seg" role="group" aria-label="Holding period">
            {study.config.horizons.map((h) => (
              <button key={h} className={h === horizon ? "on" : ""} onClick={() => setHorizon(h)}>
                {h}d
              </button>
            ))}
          </div>
        </div>
        <p className="muted small">
          <span className="key pos" /> profitable after costs <span className="key neg" /> loses after costs · trade
          direction is fixed in advance (short for ▼ signals, long otherwise) · ✓ = survives correction · hover a row
          for details
        </p>
        <div className="facets">
          {byBucket.map(([bucket, rs]) => (
            <DivergingChart
              key={bucket}
              bucket={bucket}
              results={rs}
              maxAbs={maxAbs}
              cost={study.config.costs_round_trip[bucket] ?? 0}
              borrowApr={study.config.borrow_apr_for_shorts?.[bucket] ?? 0}
            />
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Coverage and survivorship</h2>
        <table className="data">
          <thead>
            <tr>
              <th>Size</th>
              <th>Sampled</th>
              <th>No ticker now</th>
              <th>No price data</th>
              <th>With prices</th>
              <th>Events measured</th>
              <th>Ordinary-day drift (20d)</th>
            </tr>
          </thead>
          <tbody>
            {BUCKET_ORDER.filter((b) => study.coverage[b]).map((b) => {
              const c = study.coverage[b];
              const sampled = (c.companies ?? 0) + (c.no_ticker ?? 0);
              return (
                <tr key={b}>
                  <td>{SIZE_LABELS[b]}</td>
                  <td>{sampled}</td>
                  <td>
                    {c.no_ticker ?? 0} <span className="muted">({Math.round((100 * (c.no_ticker ?? 0)) / Math.max(sampled, 1))}%)</span>
                  </td>
                  <td>{c.no_prices ?? 0}</td>
                  <td>{c.with_prices ?? 0}</td>
                  <td>{(c.measured_events ?? 0).toLocaleString()}</td>
                  <td>{study.testing.baseline?.[b] ? pct(study.testing.baseline[b].mean_20) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="muted small">
          &quot;No ticker now&quot; is mostly companies that delisted, went bankrupt or were acquired since 2023. They
          are missing from the returns, so results lean optimistic, especially for small companies. Ordinary-day drift is the average 20-day return vs the index for the same stocks on non-event days: the bar a signal has to beat.
        </p>
      </section>

      <section className="panel">
        <h2>All results</h2>
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                <th>Size</th>
                <th>Signal</th>
                <th>Hold</th>
                <th>n</th>
                <th>Day-0 reaction</th>
                <th>Drift vs index</th>
                <th>Ordinary days</th>
                <th>Excess</th>
                <th>t vs ordinary</th>
                <th>Median</th>
                <th>Net</th>
                <th>Hit rate</th>
                <th>t</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {study.results.map((r) => (
                <tr key={`${r.bucket}-${r.signal}-${r.horizon_days}`} className={r.significant ? "row-sig" : ""}>
                  <td>{r.bucket}</td>
                  <td>
                    {r.direction === "-" ? "▼" : r.direction === "+" ? "▲" : "◆"} {r.label}
                  </td>
                  <td>{r.horizon_days}d</td>
                  <td>{r.n}</td>
                  <td>{pct(r.mean_reaction)}</td>
                  <td>{pct(r.mean_abnormal)}</td>
                  <td>{r.baseline_mean === null ? "—" : pct(r.baseline_mean)}</td>
                  <td>{r.excess_vs_baseline === null ? "—" : pct(r.excess_vs_baseline)}</td>
                  <td>{r.t_vs_baseline ?? "—"}</td>
                  <td>{pct(r.median_abnormal)}</td>
                  <td>{pct(r.mean_net)}</td>
                  <td>{Math.round(r.hit_rate * 100)}%</td>
                  <td>{r.t_stat}</td>
                  <td>{r.significant ? "Significant" : r.nominal_significant ? "Nominal only" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>Caveats</h2>
        <ul className="caveats">
          {study.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <p className="muted small">
          Prices: {study.config.price_source}. Size: {study.config.size_measured}. Benchmarks:{" "}
          {Object.entries(study.config.benchmark)
            .map(([b, s]) => `${b} → ${s}`)
            .join(", ")}
          .
        </p>
      </section>
    </main>
  );
}
