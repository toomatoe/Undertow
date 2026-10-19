"use client";

import { useMemo, useState } from "react";

import { pct } from "@/lib/format";
import { histogram, simulateSurvivorship } from "@/lib/learn/simulations";

import { Histogram } from "./charts";
import { NumberField, RangeField, SeedField } from "./controls";
import styles from "./learn.module.css";
import { LiveTag, Stat } from "./parts";

/** Every firm has an outcome, but the worst ones can delist and vanish before anyone measures them. */
export default function SurvivorshipSimulator() {
  const [firms, setFirms] = useState(400);
  const [trueMean, setTrueMean] = useState(-0.02);
  const [tail, setTail] = useState(0.2);
  const [delist, setDelist] = useState(0.6);
  const [seed, setSeed] = useState(3);

  const res = useMemo(
    () => simulateSurvivorship({ seed, firms, trueMean, delistProb: delist, tailShare: tail }),
    [seed, firms, trueMean, delist, tail],
  );
  const all = useMemo(() => histogram(res.returns, -1, 1, 40), [res]);
  const gone = useMemo(() => histogram(res.returns.filter((_, i) => res.vanished[i]), -1, 1, 40), [res]);
  const bias = res.measuredMean - res.trueMeanSample;

  return (
    <section className={styles.panel} aria-label="Survivorship bias simulator">
      <h3>Simulator: measure only the companies that are still around</h3>
      <p className="small">
        {firms} hypothetical companies each have a 20-day abnormal return (fat-tailed, true mean {pct(trueMean)}). Among the worst{" "}
        {Math.round(tail * 100)}% of outcomes, each company delists with probability {Math.round(delist * 100)}% and loses its ticker and
        price history, so a study that starts from today&apos;s ticker list never sees it.
      </p>
      <div className={styles.controls}>
        <NumberField label="Companies" value={firms} onChange={(v) => setFirms(Math.round(v))} min={20} max={5000} />
        <RangeField label="True mean" value={trueMean} onChange={setTrueMean} min={-0.1} max={0.05} step={0.005} format={(v) => pct(v)} />
        <RangeField label="Losing tail" value={tail} onChange={setTail} min={0} max={0.5} step={0.05} format={(v) => `worst ${Math.round(v * 100)}%`} />
        <RangeField label="Delist chance in tail" value={delist} onChange={setDelist} min={0} max={1} step={0.05} format={(v) => `${Math.round(v * 100)}%`} />
        <SeedField seed={seed} onChange={setSeed} />
      </div>
      <div className={styles.stats}>
        <Stat label="True mean (all companies)" value={pct(res.trueMeanSample, 2)} />
        <Stat label="Measured mean (survivors)" value={pct(res.measuredMean, 2)} />
        <Stat label="Bias from vanished names" value={pct(bias, 2)} sub={bias > 0 ? "flatters the result" : "no flattering"} />
        <Stat label="Vanished" value={`${res.lost} of ${firms}`} />
      </div>
      <Histogram
        bins={all}
        overlay={gone}
        title="20-day abnormal returns, all hypothetical companies"
        desc={`${res.lost} companies vanished (red); the measured mean is ${pct(res.measuredMean, 2)} vs a true ${pct(res.trueMeanSample, 2)}.`}
        cuts={[
          { x: res.trueMeanSample, label: "true" },
          { x: res.measuredMean, strong: true, label: "measured" },
        ]}
        xFormat={(v) => `${Math.round(v * 100)}%`}
      />
      <p className="muted small">
        <LiveTag kind="hypothetical" what="random numbers, seed-reproducible" /> Grey: companies still listed. Red: companies that
        delisted and fell out of the data. For a strategy that gains when prices fall, the missing losers hide gains in the study, but in
        real trading those are exactly the names that are hardest to borrow and get recalled.
      </p>
    </section>
  );
}
