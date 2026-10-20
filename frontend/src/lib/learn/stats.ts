// Pure, deterministic statistics for the Learn lessons and widgets. No React, no DOM: safe on the
// server and in the browser. Each formula mirrors the backend function named in its comment, so a
// widget shows the same arithmetic Afterfile runs:
//   backend/app/research/eventstudy.py  t_stat, welch_t, clustered_se, clustered_t, clustered_welch_t, winsorize, percentile
//   backend/app/backtest/stats.py       moments, psr, expected_max_sharpe, dsr
// References: Bailey & López de Prado (2012) "The Sharpe Ratio Efficient Frontier" (PSR);
// Bailey & López de Prado (2014) "The Deflated Sharpe Ratio" (DSR, expected maximum Sharpe).

export const TRADING_DAYS = 252;
export const EULER_GAMMA = 0.5772156649;

// --- Seeded randomness -----------------------------------------------------------------

/** mulberry32: a tiny 32-bit seeded PRNG. Same seed, same sequence, on every machine. Returns floats in [0, 1). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Standard normal draws from a uniform source (Box-Muller, one draw per call, deterministic for the source). */
export function normalSampler(rand: () => number): () => number {
  return () => {
    const u = 1 - rand(); // (0, 1]: log(0) never happens
    const v = rand();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
}

/**
 * Student-t draws with `df` degrees of freedom (integer >= 1), scaled to unit variance when df > 2.
 * Fat tails like small-cap returns: z / sqrt(chi2_df / df).
 */
export function studentTSampler(rand: () => number, df: number, unitVariance = true): () => number {
  const z = normalSampler(rand);
  const k = Math.max(1, Math.round(df));
  const scale = unitVariance && k > 2 ? Math.sqrt((k - 2) / k) : 1;
  return () => {
    let chi2 = 0;
    for (let i = 0; i < k; i++) {
      const x = z();
      chi2 += x * x;
    }
    return (z() / Math.sqrt(chi2 / k)) * scale;
  };
}

// --- Normal distribution ------------------------------------------------------------------

/** Complementary error function. Series below |x| = 3, continued fraction above (|error| < 1e-12). */
export function erfc(x: number): number {
  if (!Number.isFinite(x)) return x > 0 ? 0 : 2;
  const ax = Math.abs(x);
  let r: number;
  if (ax < 3) {
    // erf(x) = 2/sqrt(pi) * sum_n (-1)^n x^(2n+1) / (n! (2n+1))
    let term = ax;
    let sum = ax;
    const x2 = ax * ax;
    for (let n = 1; n < 120; n++) {
      term *= -x2 / n;
      const add = term / (2 * n + 1);
      sum += add;
      if (Math.abs(add) < 1e-17 * Math.abs(sum)) break;
    }
    r = 1 - (2 / Math.sqrt(Math.PI)) * sum;
  } else {
    // erfc(x) = exp(-x^2)/sqrt(pi) / (x + (1/2)/(x + 1/(x + (3/2)/(x + ...))))
    let f = ax;
    for (let k = 80; k >= 1; k--) f = ax + k / 2 / f;
    r = Math.exp(-ax * ax) / Math.sqrt(Math.PI) / f;
  }
  return x >= 0 ? r : 2 - r;
}

/** Standard normal CDF, as statistics.NormalDist().cdf. */
export function normCdf(x: number): number {
  return 0.5 * erfc(-x / Math.SQRT2);
}

/** Standard normal quantile, Wichura's AS241 (the algorithm behind Python's NormalDist.inv_cdf). */
export function normInv(p: number): number {
  if (!(p > 0 && p < 1)) {
    if (p === 0) return -Infinity;
    if (p === 1) return Infinity;
    return NaN;
  }
  const q = p - 0.5;
  if (Math.abs(q) <= 0.425) {
    const r = 0.180625 - q * q;
    const num =
      ((((((2509.0809287301226727 * r + 33430.575583588128105) * r + 67265.770927008700853) * r + 45921.953931549871457) * r +
        13731.693765509461125) * r + 1971.5909503065514427) * r + 133.14166789178437745) * r + 3.387132872796366608;
    const den =
      ((((((5226.495278852545925 * r + 28729.085735721942674) * r + 39307.89580009271061) * r + 21213.794301586595867) * r +
        5394.1960214247511077) * r + 687.1870074920579083) * r + 42.313330701600911252) * r + 1.0;
    return (q * num) / den;
  }
  let r = q <= 0 ? p : 1 - p;
  r = Math.sqrt(-Math.log(r));
  let x: number;
  if (r <= 5) {
    r -= 1.6;
    const num =
      ((((((7.7454501427834140764e-4 * r + 0.0227238449892691845833) * r + 0.24178072517745061177) * r + 1.27045825245236838258) * r +
        3.64784832476320460504) * r + 5.7694972214606914055) * r + 4.6303378461565452959) * r + 1.42343711074968357734;
    const den =
      ((((((1.05075007164441684324e-9 * r + 5.475938084995344946e-4) * r + 0.0151986665636164571966) * r + 0.14810397642748007459) * r +
        0.68976733498510000455) * r + 1.6763848301838038494) * r + 2.05319162663775882187) * r + 1.0;
    x = num / den;
  } else {
    r -= 5;
    const num =
      ((((((2.01033439929228813265e-7 * r + 2.71155556874348757815e-5) * r + 0.0012426609473880784386) * r + 0.026532189526576123093) * r +
        0.29656057182850489123) * r + 1.7848265399172913358) * r + 5.4637849111641143699) * r + 6.6579046435011037772;
    const den =
      ((((((2.04426310338993978564e-15 * r + 1.4215117583164458887e-7) * r + 1.8463183175100546818e-5) * r + 7.868691311456132591e-4) * r +
        0.0148753612908506148525) * r + 0.13692988092273580531) * r + 0.59983220655588793769) * r + 1.0;
    x = num / den;
  }
  return q < 0 ? -x : x;
}

// --- Student t distribution -----------------------------------------------------------------

function logGamma(z: number): number {
  // Lanczos approximation (g = 7, n = 9)
  const c = [
    0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059, 12.507343278686905,
    -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
  ];
  if (z < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - logGamma(1 - z);
  z -= 1;
  let x = c[0];
  for (let i = 1; i < 9; i++) x += c[i] / (z + i);
  const t = z + 7.5;
  return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}

function betacf(a: number, b: number, x: number): number {
  // Continued fraction for the incomplete beta function (modified Lentz).
  const tiny = 1e-300;
  let c = 1;
  let d = 1 - ((a + b) * x) / (a + 1);
  if (Math.abs(d) < tiny) d = tiny;
  d = 1 / d;
  let h = d;
  for (let m = 1; m <= 300; m++) {
    const m2 = 2 * m;
    let aa = (m * (b - m) * x) / ((a + m2 - 1) * (a + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < tiny) d = tiny;
    c = 1 + aa / c;
    if (Math.abs(c) < tiny) c = tiny;
    d = 1 / d;
    h *= d * c;
    aa = (-(a + m) * (a + b + m) * x) / ((a + m2) * (a + m2 + 1));
    d = 1 + aa * d;
    if (Math.abs(d) < tiny) d = tiny;
    c = 1 + aa / c;
    if (Math.abs(c) < tiny) c = tiny;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < 1e-15) break;
  }
  return h;
}

/** Regularized incomplete beta I_x(a, b). */
export function incompleteBeta(x: number, a: number, b: number): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const bt = Math.exp(logGamma(a + b) - logGamma(a) - logGamma(b) + a * Math.log(x) + b * Math.log(1 - x));
  return x < (a + 1) / (a + b + 2) ? (bt * betacf(a, b, x)) / a : 1 - (bt * betacf(b, a, 1 - x)) / b;
}

/** Student-t CDF with df degrees of freedom. */
export function tCdf(t: number, df: number): number {
  const x = df / (df + t * t);
  const tail = 0.5 * incompleteBeta(x, df / 2, 0.5);
  return t >= 0 ? 1 - tail : tail;
}

/** Two-sided p-value of a t statistic (normal when df is Infinity). */
export function twoSidedP(t: number, df = Infinity): number {
  const a = Math.abs(t);
  return Number.isFinite(df) ? 2 * (1 - tCdf(a, df)) : 2 * (1 - normCdf(a));
}

// --- Descriptive statistics (eventstudy.py) -------------------------------------------------

export function mean(xs: readonly number[]): number {
  return xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0;
}

/** Sample variance (n - 1), as statistics.variance. */
export function variance(xs: readonly number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1);
}

export const stdev = (xs: readonly number[]) => Math.sqrt(variance(xs));

export function median(xs: readonly number[]): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** eventstudy.t_stat: mean / (sd / sqrt(n)); 0 below 2 values or with no spread. */
export function tStat(xs: readonly number[]): number {
  if (xs.length < 2) return 0;
  const sd = stdev(xs);
  return sd > 0 ? mean(xs) / (sd / Math.sqrt(xs.length)) : 0;
}

/** eventstudy.welch_t: (mean a - mean b) / sqrt(var a / n_a + var b / n_b). */
export function welchT(a: readonly number[], b: readonly number[]): number {
  if (a.length < 2 || b.length < 2) return 0;
  const se = Math.sqrt(variance(a) / a.length + variance(b) / b.length);
  return se > 0 ? (mean(a) - mean(b)) / se : 0;
}

/**
 * eventstudy.clustered_se: CR1 cluster-robust standard error of the mean, null below 2 clusters.
 * se = sqrt(G/(G-1) * sum_g (sum_{i in g} (x_i - mean))^2) / n
 */
export function clusteredSe<K>(values: readonly number[], clusters: readonly K[]): number | null {
  const n = values.length;
  if (n !== clusters.length) throw new Error("values and clusters must have the same length");
  const m = n ? mean(values) : 0;
  const sums = new Map<K, number>();
  values.forEach((x, i) => sums.set(clusters[i], (sums.get(clusters[i]) ?? 0) + (x - m)));
  const g = sums.size;
  if (g < 2) return null;
  let ss = 0;
  for (const s of sums.values()) ss += s * s;
  return Math.sqrt((g / (g - 1)) * ss) / n;
}

/** eventstudy.clustered_t: firm-clustered (CR1) t of the mean vs zero; 0 below 2 clusters or with no spread. */
export function clusteredT<K>(values: readonly number[], clusters: readonly K[]): number {
  const se = clusteredSe(values, clusters);
  return se ? mean(values) / se : 0;
}

/** eventstudy.clustered_welch_t: (mean a - mean b) / sqrt(se_a^2 + se_b^2), each SE clustered (covariance ignored). */
export function clusteredWelchT<K>(a: readonly number[], ca: readonly K[], b: readonly number[], cb: readonly K[]): number {
  const sa = clusteredSe(a, ca);
  const sb = clusteredSe(b, cb);
  if (sa === null || sb === null) return 0;
  const se = Math.sqrt(sa * sa + sb * sb);
  return se > 0 ? (mean(a) - mean(b)) / se : 0;
}

/** eventstudy.percentile: linear interpolation on sorted values, q in [0, 1]. */
export function percentile(sorted: readonly number[], q: number): number {
  if (!sorted.length) return 0;
  const k = (sorted.length - 1) * q;
  const f = Math.floor(k);
  const c = Math.ceil(k);
  return sorted[f] + (sorted[c] - sorted[f]) * (k - f);
}

/** eventstudy.winsorize: clip every value into [lo, hi]. */
export function winsorize(values: readonly number[], lo: number, hi: number): number[] {
  return values.map((v) => Math.min(Math.max(v, lo), hi));
}

/** Winsorize at the 1st/99th percentile of the values themselves (the bucket bounds of eventstudy.winsor_bounds). */
export function winsorizePct(values: readonly number[], lowQ = 0.01, highQ = 0.99): number[] {
  const s = [...values].sort((a, b) => a - b);
  return winsorize(values, percentile(s, lowQ), percentile(s, highQ));
}

/**
 * Bonferroni critical |t| for nTests two-sided tests at family-wise alpha:
 * NormalDist().inv_cdf(1 - alpha / (2 * nTests)), as eventstudy.summarize (102 tests -> 3.49).
 */
export function bonferroniT(nTests: number, alpha = 0.05): number {
  return normInv(1 - alpha / (2 * Math.max(1, nTests)));
}

// --- Sharpe statistics (backtest/stats.py) ------------------------------------------------

/** stats.moments: (skewness, kurtosis) with population sd; kurtosis is the plain fourth moment (normal = 3). */
export function moments(rets: readonly number[]): { skew: number; kurt: number } {
  const n = rets.length;
  if (n < 4) return { skew: 0, kurt: 3 };
  const m = mean(rets);
  const sd = Math.sqrt(rets.reduce((s, r) => s + (r - m) ** 2, 0) / n);
  if (sd === 0) return { skew: 0, kurt: 3 };
  const skew = rets.reduce((s, r) => s + (r - m) ** 3, 0) / n / sd ** 3;
  const kurt = rets.reduce((s, r) => s + (r - m) ** 4, 0) / n / sd ** 4;
  return { skew, kurt };
}

export interface SharpeInputs {
  /** Annualized Sharpe ratio (sqrt(252) scaling, zero risk-free rate). */
  sharpeAnnual: number;
  /** Number of daily returns. */
  n: number;
  /** Skewness of daily returns (normal = 0). */
  skew: number;
  /** Kurtosis of daily returns, plain fourth moment (normal = 3). */
  kurt: number;
}

/**
 * Probabilistic Sharpe Ratio from summary statistics (Bailey & López de Prado 2012), as stats.psr:
 * PSR = Phi((SR - SR*) * sqrt(n - 1) / sqrt(1 - skew * SR + (kurt - 1) / 4 * SR^2)), SR per period.
 * Returns 0 for n < 10 or a non-positive denominator, like the backend.
 */
export function psrFromStats(x: SharpeInputs, benchmarkSharpeAnnual = 0): number {
  if (x.n < 10) return 0;
  const sr = x.sharpeAnnual / Math.sqrt(TRADING_DAYS);
  const srStar = benchmarkSharpeAnnual / Math.sqrt(TRADING_DAYS);
  const denom = 1 - x.skew * sr + ((x.kurt - 1) / 4) * sr * sr;
  if (denom <= 0) return 0;
  return normCdf(((sr - srStar) * Math.sqrt(x.n - 1)) / Math.sqrt(denom));
}

/** stats.psr on a list of daily returns. */
export function psr(rets: readonly number[], benchmarkSharpeAnnual = 0): number {
  const n = rets.length;
  if (n < 10) return 0;
  const sd = stdev(rets);
  if (sd === 0) return 0;
  const { skew, kurt } = moments(rets);
  return psrFromStats({ sharpeAnnual: (mean(rets) / sd) * Math.sqrt(TRADING_DAYS), n, skew, kurt }, benchmarkSharpeAnnual);
}

/** The factor E[max of N standard normals] used by expected_max_sharpe (Bailey & López de Prado 2014). */
export function expectedMaxFactor(nTrials: number): number {
  if (nTrials < 2) return 0;
  return (1 - EULER_GAMMA) * normInv(1 - 1 / nTrials) + EULER_GAMMA * normInv(1 - 1 / (nTrials * Math.E));
}

/**
 * Annualized Sharpe the best of nTrials would reach by luck when every true Sharpe is zero,
 * given the standard deviation of the trials' Sharpe ratios. stats.expected_max_sharpe takes the
 * list of trial Sharpes and uses its sample sd; this takes the sd directly.
 */
export function expectedMaxSharpe(sdTrialSharpes: number, nTrials: number): number {
  return nTrials < 2 ? 0 : sdTrialSharpes * expectedMaxFactor(nTrials);
}

/** stats.expected_max_sharpe(trial_sharpes, len(trial_sharpes)). */
export function expectedMaxSharpeFromTrials(trialSharpesAnnual: readonly number[]): number {
  if (trialSharpesAnnual.length < 2) return 0;
  return expectedMaxSharpe(stdev(trialSharpesAnnual), trialSharpesAnnual.length);
}

/** Deflated Sharpe Ratio: PSR against the luck benchmark of nTrials (Bailey & López de Prado 2014), as stats.dsr. */
export function dsr(x: SharpeInputs, sdTrialSharpes: number, nTrials: number): { dsr: number; benchmark: number } {
  const benchmark = expectedMaxSharpe(sdTrialSharpes, nTrials);
  return { dsr: psrFromStats(x, benchmark), benchmark };
}
