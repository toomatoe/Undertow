// Pure simulations behind the Learn widgets. Same inputs and seed -> same output, everywhere.
// Everything here is hypothetical: random numbers, not market data.

import { bonferroniT, clusteredT, mean, mulberry32, normalSampler, studentTSampler, tStat } from "./stats";

// --- Multiple testing: pure-noise signals ------------------------------------------------------

export interface NoiseParams {
  seed: number;
  /** Number of signals tested (Afterfile's grid ran 102). */
  signals: number;
  /** Events per signal. */
  events: number;
  /** Student-t degrees of freedom for the fake returns (fat tails); 0 = normal. */
  df: number;
  alpha?: number;
}

export interface NoiseResult {
  tStats: number[];
  nominal: number; // |t| >= 1.96
  bonferroni: number; // |t| >= Bonferroni cutoff
  tCritical: number;
  expectedNominal: number; // 5% of the signals
}

/** N signals whose true mean is exactly zero: how many look like discoveries at 1.96 vs the Bonferroni cutoff? */
export function simulateNoise(p: NoiseParams): NoiseResult {
  const rand = mulberry32(p.seed);
  const draw = p.df > 2 ? studentTSampler(rand, p.df) : normalSampler(rand);
  const tStats: number[] = [];
  for (let s = 0; s < p.signals; s++) {
    const xs: number[] = [];
    for (let i = 0; i < p.events; i++) xs.push(0.1 * draw()); // 10% sd per event, mean 0
    tStats.push(tStat(xs));
  }
  const alpha = p.alpha ?? 0.05;
  const tCritical = bonferroniT(p.signals, alpha);
  return {
    tStats,
    nominal: tStats.filter((t) => Math.abs(t) >= 1.96).length,
    bonferroni: tStats.filter((t) => Math.abs(t) >= tCritical).length,
    tCritical,
    expectedNominal: alpha * p.signals,
  };
}

// --- Clustered errors: events concentrated in a few firms -------------------------------------

export interface ClusterParams {
  seed: number;
  firms: number;
  eventsPerFirm: number;
  /** Share of each event's variance that is a firm-wide effect shared by all its events (0..1). */
  firmShare: number;
  /** Replications used for the false-positive rates. */
  reps: number;
}

export interface ClusterResult {
  /** One example sample: its naive and clustered t. */
  example: { naiveT: number; clusteredT: number; mean: number; n: number; firms: number };
  /** Share of replications with |t| >= 1.96, true mean zero (should be about 5%). */
  naiveRejectRate: number;
  clusteredRejectRate: number;
  naiveT: number[];
  clusteredT: number[];
}

/**
 * True mean is zero. Each firm has one shared shock (the same dilution story for all its filings),
 * so its events are not independent. The naive t treats every event as new information; the CR1
 * clustered t (eventstudy.clustered_t) counts firms.
 */
export function simulateClusters(p: ClusterParams): ClusterResult {
  const rand = mulberry32(p.seed);
  const z = normalSampler(rand);
  const share = Math.min(Math.max(p.firmShare, 0), 0.99);
  const sdFirm = 0.1 * Math.sqrt(share);
  const sdEvent = 0.1 * Math.sqrt(1 - share);
  const naive: number[] = [];
  const clustered: number[] = [];
  let example: ClusterResult["example"] | null = null;
  for (let r = 0; r < p.reps; r++) {
    const xs: number[] = [];
    const ids: number[] = [];
    for (let f = 0; f < p.firms; f++) {
      const u = sdFirm * z();
      for (let e = 0; e < p.eventsPerFirm; e++) {
        xs.push(u + sdEvent * z());
        ids.push(f);
      }
    }
    const tn = tStat(xs);
    const tc = clusteredT(xs, ids);
    naive.push(tn);
    clustered.push(tc);
    if (!example) example = { naiveT: tn, clusteredT: tc, mean: mean(xs), n: xs.length, firms: p.firms };
  }
  const rate = (ts: number[]) => (ts.length ? ts.filter((t) => Math.abs(t) >= 1.96).length / ts.length : 0);
  return {
    example: example ?? { naiveT: 0, clusteredT: 0, mean: 0, n: 0, firms: p.firms },
    naiveRejectRate: rate(naive),
    clusteredRejectRate: rate(clustered),
    naiveT: naive,
    clusteredT: clustered,
  };
}

// --- Survivorship: losers delist and vanish from the sample ------------------------------------

export interface SurvivorParams {
  seed: number;
  firms: number;
  /** True mean 20-day abnormal return of every firm (e.g. -0.02). */
  trueMean: number;
  /** Probability that a firm in the worst `tailShare` of outcomes delists and loses its data. */
  delistProb: number;
  /** Share of firms counted as the losing tail (0..1). */
  tailShare: number;
}

export interface SurvivorResult {
  returns: number[];
  vanished: boolean[];
  trueMeanSample: number;
  measuredMean: number;
  kept: number;
  lost: number;
}

/** Every firm's outcome exists, but the worst ones can vanish (no ticker, no prices) before anyone measures them. */
export function simulateSurvivorship(p: SurvivorParams): SurvivorResult {
  const rand = mulberry32(p.seed);
  const draw = studentTSampler(rand, 4);
  const returns: number[] = [];
  for (let i = 0; i < p.firms; i++) returns.push(p.trueMean + 0.25 * draw());
  const sorted = [...returns].sort((a, b) => a - b);
  const cutIdx = Math.floor(Math.min(Math.max(p.tailShare, 0), 1) * (sorted.length - 1));
  const cut = sorted.length ? sorted[cutIdx] : 0;
  const vanished = returns.map((r) => p.tailShare > 0 && r <= cut && rand() < p.delistProb);
  const kept = returns.filter((_, i) => !vanished[i]);
  return {
    returns,
    vanished,
    trueMeanSample: mean(returns),
    measuredMean: mean(kept),
    kept: kept.length,
    lost: returns.length - kept.length,
  };
}

// --- Histogram helper ------------------------------------------------------------------------

export interface Bin {
  lo: number;
  hi: number;
  count: number;
}

/** Fixed-width bins over [lo, hi]; values outside are clamped into the edge bins. */
export function histogram(values: readonly number[], lo: number, hi: number, bins: number): Bin[] {
  const width = (hi - lo) / bins;
  const out: Bin[] = Array.from({ length: bins }, (_, i) => ({ lo: lo + i * width, hi: lo + (i + 1) * width, count: 0 }));
  for (const v of values) {
    const i = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / width)));
    out[i].count += 1;
  }
  return out;
}
