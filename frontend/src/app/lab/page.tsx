"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import ConfirmatoryBlock from "@/components/learn/ConfirmatoryBlock";
import { fmtT, LiveTag, RepoPath } from "@/components/learn/parts";
import ResearchRunPanel from "@/components/ResearchRunPanel";
import { api, type EventStudy, type ResearchJobKind, type StudyInfo, type StudyName, type StudyResult } from "@/lib/api";
import { pct, pctAbs, SIZE_LABELS } from "@/lib/format";
import { dateLabel } from "@/lib/learn/live";

const BUCKET_ORDER = ["nano", "micro", "small", "mid", "large"];

const STUDIES: { key: StudyName; label: string; kind: ResearchJobKind; about: string }[] = [
  { key: "main", label: "In-sample (main)", kind: "event_study", about: "the live evidence behind every signal card" },
  { key: "oos", label: "Out-of-sample 2020–23", kind: "event_study_oos", about: "pre-registered replication on earlier years and fresh companies" },
  { key: "insider_purchases", label: "Insider purchases", kind: "insider_study", about: "open-market purchases by company insiders (Form 4), pre-registered" },
];

/** Additive fields some study files carry beyond EventStudy (insider study). */
type LabResult = StudyResult & { significant_unclustered?: boolean };
type LabStudy = Omit<EventStudy, "results" | "testing"> & {
  results: LabResult[];
  testing: EventStudy["testing"] & { significance_rule?: string };
  opportunistic_vs_routine?: {
    bucket: string;
    horizon_days: number;
    n_opportunistic: number;
    n_routine: number;
    mean_abnormal_opportunistic: number;
    mean_abnormal_routine: number;
    difference: number;
    expected_way: boolean;
  }[];
};

const cellKey = (r: { signal: string; bucket: string; horizon_days: number }) => `${r.signal}/${r.bucket}/${r.horizon_days}d`;
const sortCells = (a: StudyResult, b: StudyResult) =>
  BUCKET_ORDER.indexOf(a.bucket) - BUCKET_ORDER.indexOf(b.bucket) || a.label.localeCompare(b.label) || a.horizon_days - b.horizon_days;

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
          · {pctAbs(cost)} round trip{borrowApr > 0 && `, ▼ signals also pay ~${pctAbs(borrowApr, 0)}/yr borrow`}
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
              Measured as {hover.direction === "-" ? "a decline (sign flipped)" : "a rise"} from the day-0 close over {hover.horizon_days}d
              (hypothetical)
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
              {hover.t_stat_clustered != null && ` · clustered t = ${hover.t_stat_clustered}`}
            </span>
            <span>Day-0 reaction: {pct(hover.mean_reaction, 2)}</span>
            <span>{hover.significant ? "Survives multiple-testing correction" : "Not significant after correction"}</span>
          </div>
        )}
      </div>
    </figure>
  );
}

/** In-sample vs out-of-sample for every (signal, size, horizon) cell present in both studies. */
function Comparison({ main, oos }: { main: LabStudy; oos: LabStudy }) {
  const mainByCell = new Map(main.results.map((r) => [cellKey(r), r]));
  const confirmCells = new Set((oos.confirmatory ?? []).flatMap((c) => c.cells));
  const rows = oos.results.filter((r) => mainByCell.has(cellKey(r))).sort(sortCells);
  return (
    <section className="panel">
      <h2>In-sample vs out-of-sample</h2>
      <p className="muted small">
        Every cell tested in both studies ({rows.length}). In-sample: {main.config.window[0]} to {main.config.window[1]} (generated{" "}
        {dateLabel(main.generated_at)}). Out-of-sample: {oos.config.window[0]} to {oos.config.window[1]} (generated {dateLabel(oos.generated_at)}).
        ★ = a pre-registered confirmatory cell. Out-of-sample rows outside the confirmatory block are exploratory.
      </p>
      {rows.length === 0 ? (
        <p className="small">No cell has at least 20 events in both studies.</p>
      ) : (
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                <th>Size</th>
                <th>Signal</th>
                <th>Hold</th>
                <th>n (in / out)</th>
                <th>Drift in</th>
                <th>Drift out</th>
                <th>t in</th>
                <th>t out</th>
                <th>Clustered t in</th>
                <th>Clustered t out</th>
                <th>Net in</th>
                <th>Net out</th>
                <th>Same sign</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => {
                const m = mainByCell.get(cellKey(o))!;
                const same = Math.sign(m.mean_abnormal) === Math.sign(o.mean_abnormal);
                return (
                  <tr key={cellKey(o)} className={m.significant ? "row-sig" : ""}>
                    <td>{o.bucket}</td>
                    <td>
                      {confirmCells.has(cellKey(o)) && <span title="Pre-registered confirmatory cell">★ </span>}
                      {o.label}
                    </td>
                    <td>{o.horizon_days}d</td>
                    <td>
                      {m.n} / {o.n}
                    </td>
                    <td>{pct(m.mean_abnormal)}</td>
                    <td>{pct(o.mean_abnormal)}</td>
                    <td>{fmtT(m.t_stat)}</td>
                    <td>{fmtT(o.t_stat)}</td>
                    <td>{fmtT(m.t_stat_clustered)}</td>
                    <td>{fmtT(o.t_stat_clustered)}</td>
                    <td>{pct(m.mean_net)}</td>
                    <td>{pct(o.mean_net)}</td>
                    <td>{same ? "yes" : "no"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        <LiveTag kind="historical, hypothetical" /> Drifts are historical, market-adjusted averages; net figures assume fixed costs and
        borrow. Highlighted rows were significant in-sample.
      </p>
    </section>
  );
}

export default function LabPage() {
  const router = useRouter();
  const [infos, setInfos] = useState<StudyInfo[] | null>(null);
  const [selected, setSelected] = useState<StudyName>("main");
  const [studies, setStudies] = useState<Partial<Record<StudyName, LabStudy>>>({});
  const [errors, setErrors] = useState<Partial<Record<StudyName, string>>>({});
  const [horizon, setHorizon] = useState(20);

  // Results are stored per study, so only the newest request per study may write (reruns, StrictMode double effects).
  const requests = useRef<Partial<Record<StudyName | "infos", number>>>({});
  const load = useCallback((name: StudyName) => {
    const id = (requests.current[name] = (requests.current[name] ?? 0) + 1);
    api
      .eventStudy(name)
      .then((doc) => {
        if (id !== requests.current[name]) return;
        setStudies((cur) => ({ ...cur, [name]: doc as LabStudy }));
        setErrors((cur) => ({ ...cur, [name]: undefined }));
      })
      .catch((e) => {
        if (id === requests.current[name]) setErrors((cur) => ({ ...cur, [name]: String(e?.message ?? e) }));
      });
  }, []);

  const refreshInfos = useCallback(() => {
    const id = (requests.current.infos = (requests.current.infos ?? 0) + 1);
    api
      .studies()
      .then((list) => {
        if (id === requests.current.infos) setInfos(list);
      })
      // Older API without /api/research/studies: only the main study is known.
      .catch(() => {
        if (id === requests.current.infos) setInfos([{ study: "main", available: true, generated_at: null, n_tests: null, design: null }]);
      });
  }, []);

  useEffect(() => {
    refreshInfos();
    load("main");
  }, [refreshInfos, load]);

  // Deep links from /research: /lab?study=oos or /lab?study=insider_purchases preselect a study.
  // Also re-read on back/forward (popstate) so the selection follows the URL.
  useEffect(() => {
    const sync = () => {
      const wanted = new URLSearchParams(window.location.search).get("study");
      const match = STUDIES.find((s) => s.key === wanted);
      setSelected(match ? match.key : "main");
    };
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  const requested = useRef(new Set<StudyName>());

  const available = useCallback((name: StudyName) => infos?.find((i) => i.study === name)?.available ?? false, [infos]);

  // Load a non-main study once it is known to exist (main is loaded on mount; the OOS comparison uses it).
  useEffect(() => {
    if (selected !== "main" && available(selected) && !requested.current.has(selected)) {
      requested.current.add(selected);
      load(selected);
    }
  }, [selected, available, load]);

  const reloadSelected = useCallback(() => {
    refreshInfos();
    setErrors((cur) => ({ ...cur, [selected]: undefined }));
    load(selected);
  }, [refreshInfos, load, selected]);

  const study = studies[selected] ?? null;
  const error = errors[selected] ?? null;
  const meta = STUDIES.find((s) => s.key === selected)!;

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

  const selector = (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 16px" }}>
      <div className="seg" role="group" aria-label="Study">
        {STUDIES.map((s) => {
          const info = infos?.find((i) => i.study === s.key);
          const ok = s.key === "main" ? true : (info?.available ?? false);
          return (
            <button
              key={s.key}
              type="button"
              className={s.key === selected ? "on" : ""}
              aria-pressed={s.key === selected}
              disabled={!ok && s.key !== selected}
              title={ok ? `${s.about}${info?.generated_at ? `, generated ${dateLabel(info.generated_at)}` : ""}` : `${s.about}: not run yet`}
              onClick={() => {
                setSelected(s.key);
                router.replace(`/lab?study=${s.key}`, { scroll: false });
              }}
            >
              {s.label}
              {!ok && infos && " (not run yet)"}
            </button>
          );
        })}
      </div>
      <Link href="/research/paper" className="small">
        Read the working paper
      </Link>
    </div>
  );

  const notRun = selected !== "main" && infos !== null && !available(selected);
  const missingMain = selected === "main" && error?.startsWith("404");

  if (!study) {
    return (
      <main className="page">
        <h1>Edge Lab</h1>
        {selector}
        <ResearchRunPanel kind={meta.kind} hasReport={false} onComplete={reloadSelected} />
        {notRun || missingMain || error?.startsWith("404") ? (
          <p>
            {meta.label}: not run yet. {selected === "main" ? "Start a run above to generate the results." : "Its results appear here once it has been run."}
          </p>
        ) : error ? (
          <div role="alert">
            <p className="error">Couldn&apos;t load the study. Check the backend connection. {error}</p>
            <button onClick={reloadSelected}>Retry loading study</button>
          </div>
        ) : (
          <p role="status">Loading study…</p>
        )}
      </main>
    );
  }

  const significant = study.results.filter((r) => r.significant);
  const totalCompanies = Object.values(study.coverage).reduce((s, c) => s + (c.companies ?? 0), 0);
  const priced = Object.values(study.coverage).reduce((s, c) => s + (c.with_prices ?? 0), 0);
  const hasClustered = study.results.some((r) => r.t_stat_clustered != null);
  const hasUnclustered = study.results.some((r) => r.significant_unclustered !== undefined);
  const main = studies.main;

  return (
    <main className="page wide">
      <h1>Edge Lab</h1>
      {selector}
      <ResearchRunPanel kind={meta.kind} hasReport onComplete={reloadSelected} />
      {error && (
        <div role="alert">
          <p className="error">Couldn&apos;t refresh the study; showing the previous result. {error}</p>
          <button onClick={reloadSelected}>Retry loading study</button>
        </div>
      )}
      <p className="muted lede">
        {selected === "main"
          ? "Do SEC filing events predict how a stock moves next, after trading costs? "
          : selected === "oos"
            ? "Do the in-sample leads replicate on earlier years and companies the first study never sampled? "
            : "Did open-market purchases by company insiders predict how the stock moved next, after costs? "}
        An event study over {study.config.window[0]} to {study.config.window[1]}, with companies sorted by size at the start of the window.{" "}
        <LiveTag kind="historical" date={study.generated_at} what="generated" /> Net figures are hypothetical.
        {study.preregistration && (
          <>
            {" "}
            Pre-registered {study.preregistered_on ? `on ${study.preregistered_on}` : ""} in <RepoPath path={study.preregistration} />.
          </>
        )}
      </p>

      {selected === "oos" && <ConfirmatoryBlock study={study} />}

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

      {selected === "oos" && main && <Comparison main={main} oos={study} />}
      {selected === "oos" && !main && <p className="muted small">The in-sample study is not loaded, so the in-sample vs out-of-sample comparison is unavailable.</p>}

      <section className="panel">
        <h2>{selected === "oos" ? "What survived (exploratory grid)" : "What survived"}</h2>
        {significant.length === 0 ? (
          <p>
            Nothing. No cell produced drift that was both statistically significant after correcting for {study.testing.n_tests} tests (|t| ≥{" "}
            {study.testing.t_critical}), different from the same stocks on ordinary days, and positive after assumed costs. That is a useful
            answer: in this sample, these events alone did not show a net edge.
          </p>
        ) : (
          <ul className="findings">
            {significant.map((r) => (
              <li key={cellKey(r)}>
                <strong>{r.label}</strong> in {r.bucket} caps: {pct(r.mean_abnormal)} vs index over {r.horizon_days} trading days (n={r.n}, t=
                {r.t_stat}
                {r.t_stat_clustered != null && `, clustered t=${r.t_stat_clustered}`}). Ordinary days for the same stocks:{" "}
                {r.baseline_mean === null ? "—" : pct(r.baseline_mean)}, so the event adds {r.excess_vs_baseline === null ? "—" : pct(r.excess_vs_baseline)} (t=
                {r.t_vs_baseline}). {pct(r.mean_net)} after {pctAbs(r.cost)} assumed costs{r.borrow > 0 ? " and borrow" : ""}, measured from the
                day-0 close (hypothetical).
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">
          {study.testing.significance_rule ??
            `Significance uses a Bonferroni correction across every signal × size × horizon tested (|t| ≥ ${study.testing.t_critical}). The drift must also differ from the same stocks on ordinary days by the same margin, point the expected way, and stay positive after costs plus estimated borrow for ▼ signals. Results with |t| ≥ 1.96 that fail this are listed in the table as nominal only.`}
          {hasClustered && selected === "main" && " Clustered t-stats (by company) are shown for reference; they do not decide significance in this study."}
          {selected === "oos" && " In this study only the confirmatory block above is confirmatory; this grid is exploratory."}{" "}
          <Link href="/learn/multiple-testing">Why the bar is this high</Link>.
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
          <span className="key pos" /> positive after costs <span className="key neg" /> negative after costs · direction fixed in advance
          (decline for ▼ signals, rise otherwise) · ✓ = survives correction · hover a row for details · hypothetical net figures
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

      {study.opportunistic_vs_routine && study.opportunistic_vs_routine.length > 0 && (
        <section className="panel">
          <h2>Opportunistic vs routine insiders</h2>
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Size</th>
                  <th>Hold</th>
                  <th>n opportunistic</th>
                  <th>n routine</th>
                  <th>Drift, opportunistic</th>
                  <th>Drift, routine</th>
                  <th>Difference</th>
                  <th>Expected way</th>
                </tr>
              </thead>
              <tbody>
                {study.opportunistic_vs_routine.map((r) => (
                  <tr key={`${r.bucket}-${r.horizon_days}`}>
                    <td>{r.bucket}</td>
                    <td>{r.horizon_days}d</td>
                    <td>{r.n_opportunistic}</td>
                    <td>{r.n_routine}</td>
                    <td>{pct(r.mean_abnormal_opportunistic)}</td>
                    <td>{pct(r.mean_abnormal_routine)}</td>
                    <td>{pct(r.difference)}</td>
                    <td>{r.expected_way ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">Descriptive only, not a test (Cohen, Malloy &amp; Pomorski 2012 classification). Historical averages.</p>
        </section>
      )}

      <section className="panel">
        <h2>Coverage and survivorship</h2>
        <div className="table-scroll">
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
        </div>
        <p className="muted small">
          &quot;No ticker now&quot; is mostly companies that delisted, went bankrupt or were acquired since the size frame was taken. They are
          missing from the returns, so results lean optimistic, especially for small companies (<Link href="/learn/survivorship-bias">why</Link>).
          Ordinary-day drift is the average 20-day return vs the index for the same stocks on non-event days: the bar a signal has to beat.
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
                {hasClustered && <th>Clustered t</th>}
                {hasClustered && <th>Clusters</th>}
                <th>Verdict</th>
                {hasUnclustered && <th>Main-study rule</th>}
              </tr>
            </thead>
            <tbody>
              {study.results.map((r) => (
                <tr key={cellKey(r)} className={r.significant ? "row-sig" : ""}>
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
                  {hasClustered && <td>{fmtT(r.t_stat_clustered)}</td>}
                  {hasClustered && <td>{r.clusters ?? r.companies}</td>}
                  <td>{r.significant ? "Significant" : r.nominal_significant ? "Nominal only" : "—"}</td>
                  {hasUnclustered && <td>{r.significant_unclustered ? "Significant" : "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {hasClustered && (
          <p className="muted small">
            Clustered t: firm-clustered (CR1) t-stat, clusters = companies. <Link href="/learn/clustered-errors">What clustering changes</Link>.
          </p>
        )}
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
          . Research and education only; not investment advice.
        </p>
      </section>
    </main>
  );
}
