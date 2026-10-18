"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ResearchRunPanel from "@/components/ResearchRunPanel";

import BorrowFees from "@/components/backtest/BorrowFees";
import EquityCharts from "@/components/backtest/EquityCharts";
import { GateStatus, gateValue, label, PERIOD_TITLES, sharpeWord, Signed, SKIP_LABELS } from "@/components/backtest/parts";
import TradeLog from "@/components/backtest/TradeLog";
import Waterfall from "@/components/backtest/Waterfall";
import { api, type BacktestMetrics, type BacktestPeriod, type BacktestReport, type BacktestRunLog } from "@/lib/api";
import { fmtNum, formatMoney, formatUsd, pct, pctAbs, pctOr } from "@/lib/format";

const sharpeFmt = (v: number) => v.toFixed(2);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function Tile({ name, value, hint }: { name: string; value: React.ReactNode; hint: React.ReactNode }) {
  return (
    <div className="tile">
      <span className="muted small">{name}</span>
      <strong>{value}</strong>
      <span className="muted small">{hint}</span>
    </div>
  );
}

function HeadlineTiles({ pkey, p }: { pkey: string; p: BacktestPeriod }) {
  const m = p.metrics;
  const t = PERIOD_TITLES[pkey];
  return (
    <div className={`bt-period bt-period-${pkey}`}>
      <h3>
        {pkey}: {t?.title ?? p.period.label}
      </h3>
      <p className="muted small">
        {p.period.label} · {t?.sub}
      </p>
      <div className="tiles bt-tiles">
        <Tile name="Total return" value={<Signed v={m.total_return} fmt={(v) => pct(v)} />} hint={`${formatUsd(m.start_equity)} → ${formatUsd(m.end_equity)}`} />
        <Tile name="Per year (CAGR)" value={<Signed v={m.cagr} fmt={(v) => pct(v)} />} hint="Average yearly growth" />
        <Tile name="Sharpe ratio" value={fmtNum(m.sharpe)} hint={`Return per unit of risk: ${sharpeWord(m.sharpe)}`} />
        <Tile name="Max drawdown" value={`-${pctAbs(m.max_drawdown)}`} hint="Worst fall from a high" />
        <Tile
          name="Trades / signals"
          value={
            <>
              {m.trades} <span className="muted small">/ {m.signals}</span>
            </>
          }
          hint={`${pctAbs(m.fill_rate, 0)} of signals could be traded`}
        />
        <Tile name="Win rate" value={pctOr(m.win_rate, 0, false)} hint="Share of trades that made money" />
      </div>
    </div>
  );
}

function StressTable({ pkey, p }: { pkey: string; p: BacktestPeriod }) {
  const m = p.metrics;
  const rows = [{ label: "Base case (as designed)", total_return: m.total_return, cagr: m.cagr, sharpe: m.sharpe, max_drawdown: m.max_drawdown, trades: m.trades, base: true }, ...p.stress.map((s) => ({ ...s, base: false }))];
  return (
    <div>
      <h3 className="bt-sub">
        {pkey}: {PERIOD_TITLES[pkey]?.title ?? p.period.label}
      </h3>
      <div className="table-scroll">
        <table className="data bt-num">
          <thead>
            <tr>
              <th>Scenario</th>
              <th>Total return</th>
              <th>CAGR</th>
              <th>Sharpe</th>
              <th>Max drawdown</th>
              <th>Trades</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className={r.base ? "row-sig" : ""}>
                <td className="bt-wraptext">{r.label}</td>
                <td>
                  <Signed v={r.total_return} fmt={(v) => pct(v)} />
                </td>
                <td>
                  <Signed v={r.cagr} fmt={(v) => pct(v)} />
                </td>
                <td>
                  <Signed v={r.sharpe} fmt={sharpeFmt} />
                </td>
                <td>-{pctAbs(r.max_drawdown)}</td>
                <td>{Math.round(r.trades)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Spread({ rows }: { rows: { name: string; p05: number | null; p50: number | null; p95: number | null; fmt: (v: number) => string }[] }) {
  return (
    <table className="data bt-num">
      <thead>
        <tr>
          <th>Measure</th>
          <th>Unlucky (5th pct)</th>
          <th>Typical (median)</th>
          <th>Lucky (95th pct)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td>{r.name}</td>
            {[r.p05, r.p50, r.p95].map((v, i) => (
              <td key={i}>{v === null ? "—" : r.fmt(v)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SkippedList({ m }: { m: BacktestMetrics }) {
  const entries = Object.entries(m.skipped ?? {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <p className="muted small">None skipped.</p>;
  return (
    <table className="data bt-num">
      <tbody>
        {entries.map(([k, n]) => (
          <tr key={k}>
            <td>{label(SKIP_LABELS, k)}</td>
            <td>{n.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function BacktestPage() {
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [runs, setRuns] = useState<BacktestRunLog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);

  const loadVersion = useRef(0);
  const reload = useCallback(() => {
    const version = ++loadVersion.current;
    api.backtestReport().then((next) => {
      if (version !== loadVersion.current) return;
      setReport(next); setError(null);
    }).catch((e) => { if (version === loadVersion.current) setError(String(e.message ?? e)); });
    api.backtestRuns(50).then((next) => {
      if (version !== loadVersion.current) return;
      setRuns(next); setRunsError(null);
    }).catch((e) => { if (version === loadVersion.current) setRunsError(String(e.message ?? e)); });
  }, []);
  useEffect(() => {
    const version = loadVersion;
    reload();
    return () => { ++version.current; };
  }, [reload]);

  if (!report) {
    return (
      <main className="page">
        <h1>Backtest</h1>
        <ResearchRunPanel kind="backtest" hasReport={false} onComplete={reload} />
        {error?.startsWith("404") ? <p>No backtest yet. Start a run above to generate the report.</p> : error ? <div role="alert"><p className="error">Couldn&apos;t load the backtest. Check the backend connection. {error}</p><button onClick={reload}>Retry loading report</button></div> : <p role="status">Loading report…</p>}
      </main>
    );
  }

  const periods = Object.entries(report.periods).sort(([a], [b]) => a.localeCompare(b));
  const A = report.periods.A;
  const research = report.readiness.filter((g) => g.status !== "pending");
  const passed = research.filter((g) => g.status === "pass").length;
  const of = report.overfitting;
  const lp = report.live_projection;
  const wf = report.walk_forward;
  const [r05, r50, r95] = lp.expected_annual_return_range;

  return (
    <main className="page wide bt">
      <div>
        <h1>Backtest</h1>
        <p className="muted small">
          {report.strategy.name} · generated {new Date(report.generated_at).toLocaleString()}
        </p>
      </div>

      <ResearchRunPanel kind="backtest" hasReport onComplete={reload} />
      {error && <div role="alert"><p className="error">Couldn&apos;t refresh the report; showing the previous result. {error}</p><button onClick={reload}>Retry loading report</button></div>}

      {/* 1. Verdict */}
      <section className={`panel bt-verdict bt-${report.verdict.level}`} aria-live="polite">
        <p className="bt-verdict-kicker">{report.verdict.level === "not_ready" ? "✗ Verdict" : "◐ Verdict"}</p>
        <h2 className="bt-headline">{report.verdict.headline}</h2>
        <p>{report.verdict.detail}</p>
        {A && (
          <ul className="bt-answers">
            <li>
              <strong>Did it make money in the honest test?</strong> {A.metrics.total_return > 0 ? "Yes" : "No"}:{" "}
              {formatUsd(A.metrics.start_equity)} became {formatUsd(A.metrics.end_equity)} ({pct(A.metrics.total_return)}) from {A.period.label}.
            </li>
            <li>
              <strong>How bad did it get?</strong> At its worst the account was {pctAbs(A.metrics.max_drawdown)} below its previous high; the worst
              single month was {pct(A.metrics.worst_month)}.
            </li>
            <li>
              <strong>Is it skill or luck?</strong> After allowing for the {of.trials} variations tried, there is a {pctAbs(of.dsr_A ?? 0, 0)} chance the
              out-of-sample result reflects a real edge (we want 95%).
            </li>
            <li>
              <strong>Checklist:</strong> {passed} of {research.length} research checks pass; {report.readiness.length - research.length} operational steps are
              not started.
            </li>
          </ul>
        )}
        <p className="small bt-disclaimer">
          Simulated, hypothetical performance on historical data. No real trades were made, and results don&apos;t include every real-world cost.
          This is research, not investment advice.
        </p>
      </section>

      {report.key_finding?.text && (
        <section className="panel bt-finding">
          <h2>What we learned</h2>
          <p>{report.key_finding.text}</p>
        </section>
      )}

      {/* 2. Strategy */}
      <section className="panel">
        <h2>The strategy in plain English</h2>
        <p>{report.strategy.summary}</p>
        <p>
          <strong>Why it might work:</strong> {report.strategy.hypothesis}
        </p>
      </section>

      {/* 3. Headline tiles */}
      <section className="panel">
        <h2>Results at a glance ($100k starting balance)</h2>
        <div className="bt-two">
          {periods.map(([k, p]) => (
            <HeadlineTiles key={k} pkey={k} p={p} />
          ))}
        </div>
        <p className="muted small">
          ▲/▼ mark gains and losses. Period A is the one that counts: the signal was discovered using period B, so B&apos;s numbers are
          flattered by hindsight.
        </p>
      </section>

      {/* 3b. Where the edge goes */}
      <section className="panel">
        <h2>Where the edge goes</h2>
        <p className="muted small">
          Start with the raw price drift after a priced offering, then add one real-world friction at a time until we reach the strategy as
          simulated. Blue ▲ steps help, red ▼ steps hurt; the top and bottom bars are totals. Both periods share one scale. Hover or focus a row
          for trades, median and portfolio results.
        </p>
        <Waterfall periods={periods} />
      </section>

      {/* 3c. Borrow fees */}
      <section className="panel" id="borrow">
        <h2>Borrow fees: the cost that decides it</h2>
        <p className="muted small">
          Short sellers pay a yearly fee to borrow the shares. The same strategy rerun at different fees, with today&apos;s real fees for
          comparison.
        </p>
        <BorrowFees report={report} periods={periods} />
      </section>

      {/* 4. Equity curves */}
      <section className="panel">
        <h2>How the account grew</h2>
        <p className="muted small">
          Weekly account value starting from $100k, both periods on the same scale. The shaded chart below each shows how far the account was
          below its previous high. Hover for exact values.
        </p>
        <EquityCharts periods={periods} />
      </section>

      {/* 5. Readiness */}
      <section className="panel">
        <h2>Live-trading readiness checklist</h2>
        <p className="muted small">
          Research checks come from the backtest. Operational checks stay pending until they are built. Even if every research check
          passes, the verdict is &quot;paper trade next&quot;, never &quot;ready for real money&quot;.
        </p>
        <div className="table-scroll">
          <table className="data bt-gates">
            <thead>
              <tr>
                <th>Check</th>
                <th>Status</th>
                <th>Result</th>
                <th>Needed</th>
                <th>Why it matters</th>
              </tr>
            </thead>
            <tbody>
              {report.readiness.map((g) => (
                <tr key={g.gate}>
                  <td>{g.gate}</td>
                  <td>
                    <GateStatus status={g.status} />
                  </td>
                  <td>{gateValue(g)}</td>
                  <td>{g.threshold}</td>
                  <td className="bt-wraptext muted">{g.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 6. Live projection */}
      <section className="panel">
        <h2>If we traded this with real money</h2>
        <p className="muted small">Based on: {lp.basis}. These are ranges from resampling the backtest, not promises.</p>
        <div className="tiles">
          <Tile
            name="Expected yearly return"
            value={<Signed v={r50} fmt={(v) => pct(v)} />}
            hint={`90% range: ${pctOr(r05)} to ${pctOr(r95)}`}
          />
          <Tile name="Chance of a losing year" value={pctOr(lp.prob_losing_year, 0, false)} hint="From 1,000 resampled histories" />
          <Tile name="Worst month" value={<Signed v={lp.worst_month} fmt={(v) => pct(v)} />} hint="In the out-of-sample test" />
          <Tile name="Max drawdown" value={`-${pctAbs(lp.max_drawdown)}`} hint="Worst fall from a high" />
          <Tile name="Worst-case stress" value={<Signed v={lp.worst_case_stress_cagr} fmt={(v) => pct(v)} />} hint="Yearly return if costs, borrow and timing all go wrong" />
        </div>

        <div className="bt-two">
          <div>
            <h3 className="bt-sub">How much money can it handle?</h3>
            <div className="table-scroll">
              <table className="data bt-num">
                <thead>
                  <tr>
                    <th>Starting capital</th>
                    <th>Total return</th>
                    <th>CAGR</th>
                    <th>Sharpe</th>
                    <th>Signals filled</th>
                  </tr>
                </thead>
                <tbody>
                  {lp.capacity.map((c) => (
                    <tr key={c.capital}>
                      <td>{formatMoney(c.capital)}</td>
                      <td>
                        <Signed v={c.total_return} fmt={(v) => pct(v)} />
                      </td>
                      <td>
                        <Signed v={c.cagr} fmt={(v) => pct(v)} />
                      </td>
                      <td>{fmtNum(c.sharpe)}</td>
                      <td>{pctAbs(c.fill_rate, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">
              Bigger accounts can&apos;t trade the smallest stocks without moving the price, so fewer signals get filled.
            </p>
          </div>
          <div>
            <h3 className="bt-sub">Risks this backtest can&apos;t see</h3>
            <ul className="caveats">
              {lp.not_modeled.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        </div>

        <p className="muted small">
          Borrow availability and fees today are compared with these assumptions in <a className="bt-link" href="#borrow">Borrow fees</a> above.
        </p>
      </section>

      {/* 7. Stress tests */}
      <section className="panel">
        <h2>Stress tests: what if our assumptions are wrong?</h2>
        <p className="muted small">
          Each row changes one assumption (the last changes several at once). Stress rows average 5 random borrow draws. ▲ positive, ▼ negative.
        </p>
        <div className="bt-two">
          {periods.map(([k, p]) => (
            <StressTable key={k} pkey={k} p={p} />
          ))}
        </div>
      </section>

      {/* 8. Robustness */}
      <section className="panel">
        <h2>Robustness: is the result luck?</h2>

        <div className="bt-two">
          {periods.map(([k, p]) => (
            <div key={k}>
              <h3 className="bt-sub">
                {k}: {PERIOD_TITLES[k]?.title ?? p.period.label}
              </h3>
              <p className="muted small">
                <strong>Borrow luck</strong> ({p.monte_carlo.runs ?? "—"} runs with different random borrow and recall draws):
              </p>
              <div className="table-scroll">
                <Spread
                  rows={[
                    { name: "Sharpe", p05: num(p.monte_carlo.sharpe_p05), p50: num(p.monte_carlo.sharpe_p50), p95: num(p.monte_carlo.sharpe_p95), fmt: sharpeFmt },
                    { name: "Total return", p05: num(p.monte_carlo.total_return_p05), p50: num(p.monte_carlo.total_return_p50), p95: num(p.monte_carlo.total_return_p95), fmt: (v) => pct(v) },
                    { name: "Max drawdown", p05: num(p.monte_carlo.max_drawdown_p95), p50: num(p.monte_carlo.max_drawdown_p50), p95: num(p.monte_carlo.max_drawdown_p05), fmt: (v) => `-${pctAbs(v)}` },
                  ]}
                />
              </div>
              <p className="muted small">
                <strong>Bootstrap</strong> (daily returns reshuffled in blocks, 1,000 times):
              </p>
              {Object.keys(p.bootstrap).length ? (
                <div className="table-scroll">
                  <Spread
                    rows={[
                      { name: "Sharpe", p05: num(p.bootstrap.sharpe_p05), p50: num(p.bootstrap.sharpe_p50), p95: num(p.bootstrap.sharpe_p95), fmt: sharpeFmt },
                      { name: "Yearly return", p05: num(p.bootstrap.annual_return_p05), p50: num(p.bootstrap.annual_return_p50), p95: num(p.bootstrap.annual_return_p95), fmt: (v) => pct(v) },
                    ]}
                  />
                </div>
              ) : (
                <p className="muted small">Too little history to bootstrap.</p>
              )}
              <p className="muted small">
                Chance of a losing year: {pctOr(num(p.bootstrap.prob_losing_year), 0, false)} · Track record needed to trust this Sharpe:{" "}
                {p.min_track_record_days === null ? "more than available" : `${p.min_track_record_days.toLocaleString()} trading days`}
              </p>
            </div>
          ))}
        </div>

        <div>
          <h3 className="bt-sub">Overfitting check</h3>
          <p className="small">
            Try enough variations and one will look good by chance. The <strong>luck Sharpe</strong> is the best Sharpe you&apos;d expect from{" "}
            {of.trials} random tries with no real edge; the <strong>Deflated Sharpe</strong> is the probability the real Sharpe beats it.
          </p>
          <div className="tiles">
            <Tile name="Variations tried" value={of.trials ?? "—"} hint="Distinct search attempts ever run (stress tests and seeds excluded)" />
            {periods.map(([k, p]) => (
              <Tile
                key={k}
                name={`Deflated Sharpe (${k})`}
                value={`${pctOr(num(of[`dsr_${k}`]), 0, false)}`}
                hint={`Sharpe ${fmtNum(p.metrics.sharpe)} vs luck ${fmtNum(num(of[`luck_sharpe_${k}`]))}; want ≥ 95%`}
              />
            ))}
          </div>
        </div>

        <div>
          <h3 className="bt-sub">Walk-forward: pick settings on A, test on B</h3>
          <p className="muted small">
            Holding period and stop-loss were chosen using only period {wf.train_period}, then applied unchanged to period {wf.test_period}.
          </p>
          <div className="bt-two">
            <div className="table-scroll">
              <table className="data bt-num">
                <thead>
                  <tr>
                    <th>Hold (days)</th>
                    <th>Stop-loss</th>
                    <th>Train Sharpe</th>
                    <th>Train return</th>
                  </tr>
                </thead>
                <tbody>
                  {wf.grid.map((g) => {
                    const chosen = g.params.hold_days === wf.chosen.hold_days && g.params.stop_loss === wf.chosen.stop_loss;
                    const stop = num(g.params.stop_loss);
                    return (
                      <tr key={JSON.stringify(g.params)} className={chosen ? "row-sig" : ""}>
                        <td>
                          {chosen ? "→ " : ""}
                          {String(g.params.hold_days)}
                        </td>
                        <td>{stop === null ? "none" : `+${pctAbs(stop, 0)}`}</td>
                        <td>
                          <Signed v={g.train_sharpe} fmt={sharpeFmt} />
                        </td>
                        <td>
                          <Signed v={g.train_return} fmt={(v) => pct(v)} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="tiles bt-tiles">
              <Tile
                name="Chosen settings"
                value={<span className="small">{String(wf.chosen.hold_days)}d hold, stop {num(wf.chosen.stop_loss) === null ? "none" : `+${pctAbs(num(wf.chosen.stop_loss)!, 0)}`}</span>}
                hint="Best Sharpe on the training period"
              />
              <Tile name={`Test Sharpe (${wf.test_period})`} value={<Signed v={wf.test.sharpe} fmt={sharpeFmt} />} hint="On data it never saw" />
              <Tile name={`Test return (${wf.test_period})`} value={<Signed v={wf.test.total_return} fmt={(v) => pct(v)} />} hint={`${wf.test.trades ?? "—"} trades`} />
              <Tile name="Test max drawdown" value={`-${pctOr(wf.test.max_drawdown, 1, false)}`} hint={`Win rate ${pctOr(wf.test.win_rate, 0, false)}`} />
            </div>
          </div>
        </div>

        <div className="bt-two">
          {periods.map(([k, p]) => (
            <div key={k}>
              <h3 className="bt-sub">{k}: by filing type and by year</h3>
              <div className="table-scroll">
                <table className="data bt-num">
                  <thead>
                    <tr>
                      <th>Form</th>
                      <th>Trades</th>
                      <th>Avg return</th>
                      <th>Win rate</th>
                      <th>Net P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(p.by_form).map(([form, f]) => (
                      <tr key={form}>
                        <td>{form}</td>
                        <td>{f.trades}</td>
                        <td>
                          <Signed v={f.avg_return} fmt={(v) => pct(v)} />
                        </td>
                        <td>{pctAbs(f.win_rate, 0)}</td>
                        <td>
                          <Signed v={f.net_pnl} fmt={(v) => formatUsd(v, true)} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="table-scroll">
                <table className="data bt-num">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th>Return</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(p.yearly_returns).map(([y, r]) => (
                      <tr key={y}>
                        <td>{y}</td>
                        <td>
                          <Signed v={r} fmt={(v) => pct(v)} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">First and last years are partial.</p>
            </div>
          ))}
        </div>
      </section>

      {/* 9. Trade log */}
      <TradeLog periods={report.periods} />

      {/* 10. Run log */}
      <section className="panel">
        <h2>Run log</h2>
        {runs ? (
          <>
            <p className="small">
              <strong>{runs.total.toLocaleString()}</strong> simulations run, <strong>{runs.distinct_configs.toLocaleString()}</strong> distinct
              configurations. Of these, <strong>{(runs.search_trials ?? 0).toLocaleString()}</strong> were attempts to find a better strategy (the
              base case and walk-forward grid). Those are what the overfitting correction counts: the more we search, the higher the bar.
              Stress tests and random seeds re-check the same strategy, so they don&apos;t raise the bar. The log is never deleted.
            </p>
            <div className="table-scroll">
              <table className="data bt-num">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Period</th>
                    <th>Label</th>
                    <th>Sharpe</th>
                    <th>Return</th>
                    <th>Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.runs.slice(0, 50).map((r) => (
                    <tr key={r.id}>
                      <td>{new Date(r.at).toLocaleString()}</td>
                      <td>{r.period}</td>
                      <td className="bt-wraptext">{r.label}</td>
                      <td>{fmtNum(r.metrics.sharpe)}</td>
                      <td>{pctOr(r.metrics.total_return)}</td>
                      <td>{r.metrics.trades ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">Latest {Math.min(50, runs.runs.length)} shown.</p>
          </>
        ) : (
          <p className="muted small">{runsError ? `Run log unavailable (${runsError}).` : "Loading…"}</p>
        )}
      </section>

      {/* 11. Assumptions and skipped */}
      <section className="panel">
        <h2>Assumptions</h2>
        <ul className="caveats">
          {report.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h2>Skipped signals</h2>
        <p className="muted small">Filings that matched the strategy but weren&apos;t traded, and why.</p>
        <div className="bt-two">
          {periods.map(([k, p]) => (
            <div key={k}>
              <h3 className="bt-sub">
                {k}: {p.metrics.signals - p.metrics.trades} of {p.metrics.signals} signals skipped
              </h3>
              <div className="table-scroll">
                <SkippedList m={p.metrics} />
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
