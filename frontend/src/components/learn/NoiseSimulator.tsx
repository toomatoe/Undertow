"use client";

import { useMemo, useState } from "react";

import { histogram, simulateNoise } from "@/lib/learn/simulations";

import { Histogram } from "./charts";
import { NumberField, SeedField } from "./controls";
import styles from "./learn.module.css";
import { LiveTag, Stat } from "./parts";

/** N pure-noise signals (true mean exactly zero): count "discoveries" at |t| >= 1.96 vs the Bonferroni cutoff. */
export default function NoiseSimulator({ defaultSignals = 102 }: { defaultSignals?: number }) {
  const [signals, setSignals] = useState(defaultSignals);
  const [events, setEvents] = useState(50);
  const [fat, setFat] = useState(true);
  const [seed, setSeed] = useState(7);

  const res = useMemo(() => simulateNoise({ seed, signals, events, df: fat ? 4 : 0 }), [seed, signals, events, fat]);
  const bins = useMemo(() => histogram(res.tStats, -5, 5, 40), [res]);

  return (
    <section className={styles.panel} aria-label="Multiple-testing simulator">
      <h3>Simulator: how many pure-noise signals look significant?</h3>
      <p className="small">
        Every fake signal below has a true average return of exactly zero. Each gets {events} random event returns (10% spread
        {fat ? ", fat-tailed like small caps" : ", normally distributed"}), and we compute its t-stat the way{" "}
        <code>eventstudy.t_stat</code> does. Anything past the dashed lines would be reported as a &quot;discovery&quot;.
      </p>
      <div className={styles.controls}>
        <NumberField label="Signals tested" value={signals} onChange={(v) => setSignals(Math.round(v))} min={1} max={1000} />
        <NumberField label="Events per signal" value={events} onChange={(v) => setEvents(Math.round(v))} min={5} max={500} />
        <label>
          Return tails
          <select value={fat ? "fat" : "normal"} onChange={(e) => setFat(e.target.value === "fat")}>
            <option value="fat">Fat (Student t, 4 df)</option>
            <option value="normal">Normal</option>
          </select>
        </label>
        <SeedField seed={seed} onChange={setSeed} />
      </div>
      <div className={styles.stats}>
        <Stat label="Pass |t| ≥ 1.96 (no correction)" value={res.nominal} sub={`about ${res.expectedNominal.toFixed(1)} expected by chance`} />
        <Stat label={`Pass Bonferroni |t| ≥ ${res.tCritical.toFixed(2)}`} value={res.bonferroni} sub="chance of any: about 5% per run" />
        <Stat label="True discoveries" value={0} sub="every signal is noise" />
      </div>
      <Histogram
        bins={bins}
        title="t-stats of pure-noise signals"
        desc={`${signals} signals; ${res.nominal} beyond ±1.96 and ${res.bonferroni} beyond ±${res.tCritical.toFixed(2)}.`}
        cuts={[
          { x: -1.96, label: "-1.96" },
          { x: 1.96, label: "1.96" },
          { x: -res.tCritical, strong: true, label: `-${res.tCritical.toFixed(2)}` },
          { x: res.tCritical, strong: true, label: res.tCritical.toFixed(2) },
        ]}
        highlight={(b) => (Math.abs((b.lo + b.hi) / 2) >= res.tCritical ? "neg" : Math.abs((b.lo + b.hi) / 2) >= 1.96 ? "flag" : null)}
      />
      <p className="muted small">
        <LiveTag kind="hypothetical" what="random numbers, seed-reproducible" /> Same seed and settings give the same chart on any
        machine (mulberry32 generator). Change the seed a few times: the 1.96 count hovers around 5% of the signals; the Bonferroni count
        is usually zero.
      </p>
    </section>
  );
}
