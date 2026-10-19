"use client";

import { useMemo, useState } from "react";

import { histogram, simulateClusters } from "@/lib/learn/simulations";

import { Histogram } from "./charts";
import { NumberField, RangeField, SeedField } from "./controls";
import styles from "./learn.module.css";
import { fmtT, LiveTag, Stat } from "./parts";

const REPS = 400;

/** Events concentrated in a few firms: naive t vs firm-clustered (CR1) t, true mean zero. */
export default function ClusterSimulator() {
  const [firms, setFirms] = useState(15);
  const [perFirm, setPerFirm] = useState(20);
  const [share, setShare] = useState(0.3);
  const [seed, setSeed] = useState(11);

  const res = useMemo(
    () => simulateClusters({ seed, firms, eventsPerFirm: perFirm, firmShare: share, reps: REPS }),
    [seed, firms, perFirm, share],
  );
  const naiveBins = useMemo(() => histogram(res.naiveT, -8, 8, 40), [res]);
  const clusterBins = useMemo(() => histogram(res.clusteredT, -8, 8, 40), [res]);
  const beyond = (b: { lo: number; hi: number }) => (Math.abs((b.lo + b.hi) / 2) >= 1.96 ? ("flag" as const) : null);
  const cuts = [
    { x: -1.96, label: "-1.96" },
    { x: 1.96, label: "1.96" },
  ];

  return (
    <section className={styles.panel} aria-label="Clustered standard errors simulator">
      <h3>Simulator: {firms * perFirm} events from only {firms} companies</h3>
      <p className="small">
        The true average return is zero. Each company has one shared shock that hits all of its events (think of one dilution story
        behind several filings), plus event-level noise. The naive t-stat treats every event as independent; the clustered t-stat (
        <code>eventstudy.clustered_t</code>, CR1) treats each company as one unit of evidence. Over {REPS} repeated samples, a correct
        test should reject about 5% of the time.
      </p>
      <div className={styles.controls}>
        <NumberField label="Companies" value={firms} onChange={(v) => setFirms(Math.round(v))} min={2} max={200} />
        <NumberField label="Events per company" value={perFirm} onChange={(v) => setPerFirm(Math.round(v))} min={1} max={60} />
        <RangeField label="Shared company effect" value={share} onChange={setShare} min={0} max={0.9} step={0.05} format={(v) => `${Math.round(v * 100)}% of variance`} />
        <SeedField seed={seed} onChange={setSeed} />
      </div>
      <div className={styles.stats}>
        <Stat label="First sample: naive t" value={fmtT(res.example.naiveT)} sub={`n = ${res.example.n} events`} />
        <Stat label="First sample: clustered t" value={fmtT(res.example.clusteredT)} sub={`${res.example.firms} clusters`} />
        <Stat label="False positives, naive" value={`${(res.naiveRejectRate * 100).toFixed(1)}%`} sub="|t| ≥ 1.96, should be ~5%" />
        <Stat label="False positives, clustered" value={`${(res.clusteredRejectRate * 100).toFixed(1)}%`} sub="|t| ≥ 1.96, should be ~5%" />
      </div>
      <Histogram bins={naiveBins} title="Naive t across repeated samples" desc={`${(res.naiveRejectRate * 100).toFixed(1)}% beyond ±1.96.`} cuts={cuts} highlight={beyond} />
      <Histogram
        bins={clusterBins}
        title="Clustered t across repeated samples"
        desc={`${(res.clusteredRejectRate * 100).toFixed(1)}% beyond ±1.96.`}
        cuts={cuts}
        highlight={beyond}
      />
      <p className="muted small">
        <LiveTag kind="hypothetical" what="random numbers, seed-reproducible" /> Top: naive t. Bottom: clustered t. Set the shared effect
        to 0% and both behave; raise it and the naive test finds &quot;effects&quot; in pure noise. With very few companies even the
        clustered t over-rejects a little at 1.96 (a t-distribution with companies − 1 degrees of freedom is the stricter yardstick).
      </p>
    </section>
  );
}
