import Link from "next/link";

import { fmtNum, pct, pctOr } from "@/lib/format";
import type { Lesson } from "@/lib/learn/lessons";
import { dsrPrefill, isoDay, type DsrPrefill } from "@/lib/learn/live";
import { getBacktestReport } from "@/lib/server-api";

import { HBarChart } from "../charts";
import DsrCalculator from "../DsrCalculator";
import styles from "../learn.module.css";
import LessonLayout from "../LessonLayout";
import { ApiNote, LiveTag } from "../parts";

const ROLE: Record<string, string> = { out_of_sample: "out-of-sample", discovery: "discovery (in-sample)" };

export default async function SharpeDsrLesson({ lesson }: { lesson: Lesson }) {
  const report = await getBacktestReport();
  const bt = report.ok ? report.data : null;
  const keys = bt ? Object.keys(bt.periods).sort() : [];
  const prefill = bt ? keys.map((k) => dsrPrefill(bt, k)).filter((p): p is DsrPrefill => p !== null) : [];
  const dsrGate = bt?.readiness.find((g) => g.gate.startsWith("Deflated Sharpe"));

  return (
    <LessonLayout
      lesson={lesson}
      dataDate={isoDay(bt?.generated_at)}
      meaning={
        bt ? (
          <>
            <p>
              <LiveTag kind="hypothetical" date={bt.generated_at} what="backtest report" /> Readiness verdict: <strong>{bt.verdict.headline}</strong>{" "}
              {dsrGate && (
                <>
                  The deflated Sharpe gate ({dsrGate.threshold}) currently reads {typeof dsrGate.value === "number" ? dsrGate.value.toFixed(3) : String(dsrGate.value)}:{" "}
                  {dsrGate.status === "pass" ? "pass" : dsrGate.status === "fail" ? "fail" : "pending"}.
                </>
              )}
            </p>
            <p>
              The event study measures an average drift; the backtest is where borrow, recalls, stops and unborrowable names are added, and
              the waterfall below shows how much of the gross edge each one removes. Undertow publishes the verdict whatever it says rather
              than tuning parameters until it looks better, and every configuration ever tried counts against the deflated Sharpe ratio. Full details: <Link href="/backtest">Backtest</Link>.
            </p>
          </>
        ) : (
          <p>The backtest report could not be loaded, so the live verdict is missing. The calculator below still works with the textbook example.</p>
        )
      }
    >
      <p className={styles.lede}>
        A backtest Sharpe ratio is the best-looking number in quant finance and the easiest to fool yourself with. Three corrections turn it
        into something closer to the truth: sample length and fat tails (PSR), the number of things you tried (DSR), and the frictions you
        left out.
      </p>

      <section className={styles.section}>
        <h2>Sharpe ratio, and why the raw number misleads</h2>
        <p>
          The Sharpe ratio is the mean return divided by its standard deviation; Undertow uses daily returns, a zero risk-free rate and
          annualizes by √252. Two problems. First, a short track record produces high Sharpe ratios by chance. Second, strategies that
          collect small gains and occasionally suffer large losses (negative skew, fat tails) look smoother than they are, and the hypothetical
          nano-cap offering strategy Undertow backtests has exactly that shape.
        </p>
      </section>

      <section className={styles.section}>
        <h2>PSR: probability the true Sharpe beats a benchmark</h2>
        <p>
          The Probabilistic Sharpe Ratio (Bailey &amp; López de Prado, 2012) asks how likely it is that the true Sharpe exceeds a benchmark
          SR*, given n observations, skew γ₃ and kurtosis γ₄, with SR measured per period:
        </p>
        <p className={styles.code}>PSR = Φ( (SR − SR*) × √(n − 1) / √(1 − γ₃·SR + (γ₄ − 1)/4 · SR²) )</p>
        <p>Negative skew and high kurtosis enlarge the denominator, so the same Sharpe earns less confidence.</p>
      </section>

      <section className={styles.section}>
        <h2>DSR: deflate for every configuration tried</h2>
        <p>
          If you try N variants and keep the best, the best one&apos;s Sharpe is biased upwards even when none has any edge. The Deflated
          Sharpe Ratio (Bailey &amp; López de Prado, 2014) sets SR* to the Sharpe the best of N would reach by luck alone:
        </p>
        <p className={styles.code}>E[max SR] ≈ sd(trial SRs) × ( (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ),  γ ≈ 0.5772</p>
        <p>
          and then computes the PSR against it. Undertow logs every backtest run to <code>runs.jsonl</code> and counts distinct
          configurations (different random seeds do not count as new ideas), so the bar can only rise. The live-readiness gate requires
          DSR ≥ 0.95 on the out-of-sample period.
        </p>
      </section>

      {prefill.length === 0 && <ApiNote what="backtest report" status={report.ok ? 0 : report.status} />}
      <DsrCalculator prefill={prefill} reportDate={bt?.generated_at ?? null} />

      {bt && (
        <section className={styles.section}>
          <h2>The friction waterfall: from gross edge to net result</h2>
          <p>
            The backtester starts from a frictionless version of the strategy and adds one real-world cost at a time until it reaches the base
            case (<code>report.waterfall</code>; an assertion guarantees the last step is exactly the base configuration). Average return per
            trade at each step:
          </p>
          {keys.map((k) => {
            const p = bt.periods[k];
            if (!p?.waterfall?.length) return null;
            return (
              <div key={k} className={styles.panel}>
                <h3>
                  Period {k}: {p.period.label} ({ROLE[p.period.role] ?? p.period.role})
                </h3>
                <HBarChart
                  title={`Average return per trade by friction step, period ${k}`}
                  desc={p.waterfall.map((s) => `${s.step}: ${pct(s.avg_trade_return, 2)}`).join("; ")}
                  format={(v) => pct(v, 2)}
                  labelWidth={300}
                  data={p.waterfall.map((s) => ({ label: s.step, value: s.avg_trade_return }))}
                />
                <p className="muted small">
                  <LiveTag kind="hypothetical" date={bt.generated_at} what="backtest report" /> Trades per step:{" "}
                  {p.waterfall.map((s) => s.trades).join(" → ")}. Borrow break-even:{" "}
                  {p.borrow_sensitivity?.breakeven_apr == null
                    ? "never crosses zero in the tested range"
                    : p.borrow_sensitivity.breakeven_apr === 0
                      ? "negative even with free borrow"
                      : `${pctOr(p.borrow_sensitivity.breakeven_apr, 0, false)} a year`}
                  .
                </p>
              </div>
            );
          })}

          <h2>In-sample vs out-of-sample</h2>
          <p>
            The signal was discovered on the later period, so results there are flattered by selection. The earlier period was never used to
            find it. If a strategy only works where it was found, it was probably found by luck.
          </p>
          <div className={styles.tableScroll}>
            <table className="data">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Role</th>
                  <th>Trades</th>
                  <th>Total return</th>
                  <th>Sharpe</th>
                  <th>Max drawdown</th>
                  <th>PSR</th>
                  <th>DSR</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => {
                  const p = bt.periods[k];
                  const d = bt.overfitting?.[`dsr_${k}`];
                  return (
                    <tr key={k}>
                      <td>{p.period.label}</td>
                      <td>{ROLE[p.period.role] ?? p.period.role}</td>
                      <td>{p.metrics.trades}</td>
                      <td>{pct(p.metrics.total_return)}</td>
                      <td>{fmtNum(p.metrics.sharpe)}</td>
                      <td>{pctOr(p.metrics.max_drawdown, 1, false)}</td>
                      <td>{fmtNum(p.metrics.psr, 3)}</td>
                      <td>{typeof d === "number" ? d.toFixed(3) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            <LiveTag kind="hypothetical" date={bt.generated_at} what="backtest report" /> Simulated portfolio, hedged with IWM, all assumed costs
            included. Walk-forward check: parameters chosen on {bt.walk_forward.train_period}, then applied unchanged to {bt.walk_forward.test_period}.
          </p>
        </section>
      )}

      <section className={styles.section}>
        <h2>Look-ahead bias: using information you would not have had</h2>
        <ul>
          <li>
            <strong>Size</strong> comes from the SEC public float measured before the period starts (<code>Period.float_year</code>), not from
            today&apos;s market cap.
          </li>
          <li>
            <strong>Timing</strong> comes from the EDGAR acceptance time (<code>day0_index</code>), and the base case enters one close later
            because short-sale restrictions (Rule 201) often block trading into the day-0 drop.
          </li>
          <li>
            <strong>Liquidity</strong> is measured as the median dollar volume over the 20 days <em>before</em> entry, because the offering
            day&apos;s volume spike would overstate capacity.
          </li>
          <li>
            <strong>Price floors</strong> use the unadjusted price: nano caps reverse-split constantly, and a split-adjusted history makes a
            $0.30 stock look like $3.60.
          </li>
        </ul>
      </section>

      <section className={styles.section}>
        <h2>Borrow: the cost that decides it</h2>
        <p>
          A strategy that gains from declines must borrow shares. For nano caps right after an offering, borrow is scarce and expensive,
          lenders recall shares at the worst time, and some names cannot be borrowed at all. The backtest charges borrow daily, simulates
          recalls and unavailable shares, and reports the borrow fee at which the hypothetical strategy would break even. Daily archives of a
          broker&apos;s public shortable-stock file now track the real fees going forward.
        </p>
      </section>
    </LessonLayout>
  );
}
