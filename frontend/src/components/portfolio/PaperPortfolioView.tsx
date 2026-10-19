"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type PaperPortfolio, type PaperPosition, type PaperSignalRow } from "@/lib/api";
import { formatUsd, pct, pctOr } from "@/lib/format";

import { Signed } from "../backtest/parts";
import { formatDay, sizeShort, sizeTitle } from "../track/parts";
import EquityChart from "./EquityChart";
import styles from "./portfolio.module.css";

const CAPACITY_OPTIONS = [5, 10, 20, 50, 100];

function Tile({ name, value, hint }: { name: React.ReactNode; value: React.ReactNode; hint: React.ReactNode }) {
  return (
    <div className="tile">
      <span className="muted small">{name}</span>
      <strong>{value}</strong>
      <span className="muted small">{hint}</span>
    </div>
  );
}

export function HypotheticalBanner({ label }: { label?: string }) {
  return (
    <div className={styles.banner} role="note" aria-label="Hypothetical results">
      <strong>Hypothetical, not traded, not advice.</strong>
      <span className="small">
        {label ? (label.endsWith(".") ? label : `${label}.`) : "Simulated from the forward signal journal."} No account exists, nothing is executed, and every figure on this page is a
        simulation that includes estimated costs and borrow fees.
      </span>
    </div>
  );
}

function SideLabel({ side }: { side: PaperPosition["side"] }) {
  return <span className={styles.side}>{side === "long" ? "▲ Long" : "▼ Short"}</span>;
}

function ForwardTestBadge({ row }: { row: Pick<PaperSignalRow, "forward_test" | "forward_test_label"> }) {
  if (!row.forward_test) return null;
  return (
    <span className={styles.badge} title="Live forward test of a finding from a separate pre-registered study (hypothetical long, 5-day horizon)">
      {row.forward_test_label ? row.forward_test_label.charAt(0).toUpperCase() + row.forward_test_label.slice(1) : "Forward test"}
    </span>
  );
}

function SignalTable({ rows }: { rows: PaperSignalRow[] }) {
  return (
    <section className="panel">
      <h2>By signal type (hypothetical)</h2>
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th>Signal</th>
              <th>Side</th>
              <th>Horizon</th>
              <th>Positions</th>
              <th>Closed</th>
              <th>Hypothetical P&amp;L</th>
              <th>Mean net return (closed)</th>
              <th>Hit rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.signal}>
                <td>
                  {r.forward_test ? r.label.replace(/\s*\(forward test[^)]*\)/i, "") : r.label}
                  <ForwardTestBadge row={r} />
                </td>
                <td>{r.direction === "-" ? "▼ Short" : "▲ Long"}</td>
                <td>{r.horizon}d</td>
                <td>{r.n}</td>
                <td>{r.n_closed}</td>
                <td>
                  <Signed v={r.pnl} fmt={(v) => formatUsd(v, true)} />
                </td>
                <td>
                  <Signed v={r.mean_return_net} fmt={(v) => pct(v)} />
                </td>
                <td>{pctOr(r.hit_rate, 0, false)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PositionsTable({ positions }: { positions: PaperPosition[] }) {
  return (
    <section className="panel">
      <h2>Recent hypothetical positions</h2>
      <p className="muted small">The latest {positions.length} by entry day. Open positions are marked to the latest close.</p>
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Signal</th>
              <th>Side</th>
              <th>Size</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Net return</th>
              <th>Hypothetical P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={`${p.ticker}-${p.entry_date}-${p.signal}`}>
                <td>
                  <Link href={`/ticker/${encodeURIComponent(p.ticker)}`}>{p.ticker}</Link>
                </td>
                <td>{p.signal.replace(/_/g, " ")}</td>
                <td>
                  <SideLabel side={p.side} />
                </td>
                <td title={sizeTitle(p.size_bucket)}>{sizeShort(p.size_bucket)}</td>
                <td>{formatDay(p.entry_date)}</td>
                <td>{p.exit_date ? formatDay(p.exit_date) : <span className="muted">open ({p.horizon}d)</span>}</td>
                <td>
                  <Signed v={p.net_return} fmt={(v) => pct(v)} />
                </td>
                <td>
                  <Signed v={p.pnl} fmt={(v) => formatUsd(v, true)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Assumptions({ data }: { data: PaperPortfolio }) {
  const a = data.assumptions;
  const t = data.totals;
  const special = Object.entries(a.horizons).filter(([k]) => k !== "default");
  return (
    <section className="panel">
      <h2>Assumptions</h2>
      <ul className={styles.assumptions}>
        <li>
          One hypothetical position per journal signal, {formatUsd(a.notional)} each, opened at the same close the journal uses (the close after
          the first close the stock could trade on). Starting capital {formatUsd(a.starting_capital)} = {a.max_concurrent} slots.
        </li>
        <li>
          Long for signals expected to rise, short for signals expected to fall. Signals with no expected direction open nothing
          {t.undirected ? ` (${t.undirected} so far)` : ""}.
        </li>
        <li>
          Held for {a.horizons.default} trading days
          {special.map(([k, h]) => `; ${k.replace(/_/g, " ")} ${h} days`).join("")}.
        </li>
        <li>
          At most {a.max_concurrent} open at once; {t.skipped_capacity} signal{t.skipped_capacity === 1 ? " was" : "s were"} skipped for capacity.
        </li>
        <li>{a.cost_model}</li>
        <li>{a.hedge ? "Each position is paired with an equal and opposite IWM (small-cap index fund) position." : "No index hedge."}</li>
        <li>
          {t.unpriced} signal{t.unpriced === 1 ? "" : "s"} without cached prices and {t.pending} still waiting for an entry price are left out.
        </li>
      </ul>
      <p className="muted small">
        How each number is produced: <Link href="/methodology">Methodology</Link>. The signals themselves, with their sealed timestamps:{" "}
        <Link href="/track-record">Track record</Link>.
      </p>
    </section>
  );
}

export default function PaperPortfolioView() {
  const [hedge, setHedge] = useState(false);
  const [maxConcurrent, setMaxConcurrent] = useState(20);
  const [data, setData] = useState<PaperPortfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api
      .paperPortfolio({ hedge, max_concurrent: maxConcurrent })
      .then((d) => live && setData(d))
      .catch((e) => live && setError(String(e?.message ?? e)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [hedge, maxConcurrent]);

  const controls = (
    <div className={styles.controls} aria-label="Simulation settings">
      <label>
        <input type="checkbox" checked={hedge} onChange={(e) => setHedge(e.target.checked)} />
        Hedge each position with IWM
      </label>
      <label>
        Max open positions
        <select value={maxConcurrent} onChange={(e) => setMaxConcurrent(Number(e.target.value))}>
          {CAPACITY_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      {loading && data && <span className="muted small">Updating…</span>}
    </div>
  );

  let body: React.ReactNode;
  if (error && !data) {
    body = (
      <section className="panel">
        <p className="error">Couldn&apos;t load the paper portfolio: {error}</p>
        <p className="muted small">
          Is the API running on port 8000? An API built before this page existed needs a rebuild. The signals are still on the{" "}
          <Link href="/track-record">track record</Link>.
        </p>
      </section>
    );
  } else if (!data) {
    body = <p className="muted">Loading…</p>;
  } else if (data.empty_reason) {
    body = (
      <section className="panel">
        <h2>Nothing to show yet</h2>
        <p className="small">
          The journal is young: positions appear after signals are recorded and marked. See the <Link href="/track-record">track record</Link>{" "}
          for every signal recorded so far.
        </p>
        <p className="muted small">{data.empty_reason}</p>
      </section>
    );
  } else {
    const t = data.totals;
    const start = data.assumptions.starting_capital;
    body = (
      <>
        {error && <p className="error small">Couldn&apos;t refresh: {error}. Showing the previous result.</p>}
        <div className="tiles bt-tiles" aria-label="Hypothetical totals">
          <Tile name="Hypothetical P&L" value={<Signed v={t.pnl} fmt={(v) => formatUsd(v, true)} />} hint="After estimated costs and borrow" />
          <Tile name="Hypothetical return" value={<Signed v={t.return_pct} fmt={(v) => pct(v)} />} hint={`On ${formatUsd(start)} starting capital`} />
          <Tile name="Closed / open" value={`${t.n_closed} / ${t.n_open}`} hint={`${t.skipped_capacity} skipped for capacity`} />
          <Tile name="Hit rate" value={pctOr(t.hit_rate, 0, false)} hint="Closed positions with a net gain" />
        </div>
        <section className="panel">
          <h2>Hypothetical equity</h2>
          <p className="muted small">Simulated value of the {formatUsd(start)} book each trading day, as of {formatDay(data.as_of)}.</p>
          <EquityChart points={data.equity_curve} start={start} />
        </section>
        <SignalTable rows={data.by_signal} />
        <PositionsTable positions={data.positions} />
        <Assumptions data={data} />
      </>
    );
  }

  return (
    <main className={`${styles.root} page wide bt`}>
      <div>
        <h1>Paper portfolio</h1>
        <p className={styles.intro}>
          What an equal-weight book that took every journal signal at the journal&apos;s own entry price would look like, with estimated costs and
          borrow fees taken out. It is a calculation, not an account: nothing here is traded.
        </p>
      </div>
      <HypotheticalBanner label={data?.label} />
      {controls}
      {body}
      <p className={`muted small ${styles.foot}`}>
        Past and simulated results do not predict future results. Prices are adjusted daily closes used for personal research. Nothing on this page
        is investment advice or a recommendation about any security.
      </p>
    </main>
  );
}
