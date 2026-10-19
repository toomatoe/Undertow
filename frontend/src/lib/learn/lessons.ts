// Lesson registry for /learn. Plain data: safe on the server and in the browser.
// Every repoRefs path must exist in this repository (checked by hand in review: run
// `git ls-files <path>` for each). Paths are relative to the repo root.

export interface RepoRef {
  path: string;
  /** Function, constant or section inside the file. */
  symbol: string;
  why: string;
}

export interface Reading {
  /** Author(s) and year, e.g. "MacKinlay (1997)". Citations only, never excerpts. */
  cite: string;
  title: string;
  venue: string;
}

export interface Lesson {
  slug: string;
  title: string;
  /** Meta description (also the index blurb). Under ~160 characters. */
  description: string;
  level: "Beginner" | "Intermediate" | "Advanced";
  minutes: number;
  concepts: string[];
  repoRefs: RepoRef[];
  readings: Reading[];
}

export const READINGS = {
  mackinlay1997: { cite: "MacKinlay (1997)", title: "Event Studies in Economics and Finance", venue: "Journal of Economic Literature 35(1)" },
  loughranRitter1995: { cite: "Loughran & Ritter (1995)", title: "The New Issues Puzzle", venue: "Journal of Finance 50(1)" },
  lakonishokLee2001: { cite: "Lakonishok & Lee (2001)", title: "Are Insider Trades Informative?", venue: "Review of Financial Studies 14(1)" },
  cohenMalloyPomorski2012: { cite: "Cohen, Malloy & Pomorski (2012)", title: "Decoding Inside Information", venue: "Journal of Finance 67(3)" },
  harveyLiuZhu2016: { cite: "Harvey, Liu & Zhu (2016)", title: "…and the Cross-Section of Expected Returns", venue: "Review of Financial Studies 29(1)" },
  baileyLdp2012: { cite: "Bailey & López de Prado (2012)", title: "The Sharpe Ratio Efficient Frontier", venue: "Journal of Risk 15(2)" },
  baileyLdp2014: { cite: "Bailey & López de Prado (2014)", title: "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality", venue: "Journal of Portfolio Management 40(5)" },
  petersen2009: { cite: "Petersen (2009)", title: "Estimating Standard Errors in Finance Panel Data Sets: Comparing Approaches", venue: "Review of Financial Studies 22(1)" },
} satisfies Record<string, Reading>;

const ES = "backend/app/research/eventstudy.py";

export const LESSONS: Lesson[] = [
  {
    slug: "event-study",
    title: "Event studies explained: abnormal returns, reaction and drift",
    description:
      "How an event study measures what stocks did after an SEC filing: abnormal returns vs an index, the day-0 timing rule, and why drift differs from reaction.",
    level: "Beginner",
    minutes: 12,
    concepts: ["abnormal return", "market adjustment", "day 0", "reaction vs drift", "costs and borrow"],
    repoRefs: [
      { path: ES, symbol: "day0_index", why: "Picks the first close a trader could act on after the EDGAR acceptance time (15:30 ET cut-off)." },
      { path: ES, symbol: "measure", why: "Turns one filing into a day-0 reaction and 5/20-day drifts, each minus the benchmark over the same dates." },
      { path: ES, symbol: "summarize", why: "Averages measurements per signal, size and horizon, then subtracts costs and borrow to get mean_net." },
      { path: "backend/app/pipeline/signals.py", symbol: "signals_for_filing", why: "Maps a filing's form and 8-K items to signals, the same taxonomy as the live alerts." },
      { path: "backend/tests/test_eventstudy.py", symbol: "tests", why: "Small synthetic price series that pin down the timing and return arithmetic." },
    ],
    readings: [READINGS.mackinlay1997, READINGS.loughranRitter1995],
  },
  {
    slug: "baselines",
    title: "Why 'vs ordinary days' matters: baselines in an event study",
    description:
      "Small caps drift down even on days with no news. Learn how QuantDesk compares filing events with the same stocks on ordinary days, and why that changes results.",
    level: "Beginner",
    minutes: 8,
    concepts: ["baseline", "excess return", "Welch t-test", "small-cap drift"],
    repoRefs: [
      { path: ES, symbol: "baseline_events", why: "Ordinary-day pseudo-events: the same companies at 10:00 ET every 21 trading days." },
      { path: ES, symbol: "welch_t", why: "Tests whether event drift differs from ordinary-day drift (unequal variances)." },
      { path: ES, symbol: "summarize", why: "Builds testing.baseline and each row's baseline_mean, excess_vs_baseline and t_vs_baseline." },
    ],
    readings: [READINGS.mackinlay1997],
  },
  {
    slug: "multiple-testing",
    title: "Multiple testing and the Bonferroni correction, with a noise simulator",
    description:
      "Test 100 pure-noise signals and about five clear |t| 1.96 by chance. Simulate it, then see why QuantDesk uses a Bonferroni cutoff instead.",
    level: "Intermediate",
    minutes: 10,
    concepts: ["false discoveries", "family-wise error", "Bonferroni", "data snooping", "pre-registration"],
    repoRefs: [
      { path: ES, symbol: "summarize", why: "t_crit = NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests)) over every signal x size x horizon tested." },
      { path: "backend/app/research/PREREGISTRATION_OOS.md", symbol: "section 4", why: "A family of exactly three confirmatory tests, fixed before any out-of-sample data was seen." },
      { path: "backend/app/backtest/report.py", symbol: "build_report (overfitting)", why: "The backtest counts every configuration ever tried, the same idea applied to strategies." },
    ],
    readings: [READINGS.harveyLiuZhu2016],
  },
  {
    slug: "clustered-errors",
    title: "Clustered standard errors: when many events come from a few companies",
    description:
      "Events from the same company are not independent. Simulate naive vs firm-clustered t-stats and see how QuantDesk's nano-cap offering result holds up.",
    level: "Intermediate",
    minutes: 12,
    concepts: ["independence", "cluster-robust SE (CR1)", "effective sample size", "confirmatory test"],
    repoRefs: [
      { path: ES, symbol: "clustered_se", why: "CR1 cluster-robust standard error of the mean, clusters = companies." },
      { path: ES, symbol: "clustered_t", why: "Reported next to every plain t-stat as t_stat_clustered." },
      { path: "backend/app/research/oos.py", symbol: "confirmatory", why: "The out-of-sample verdicts use the clustered t against a Bonferroni family of 3." },
      { path: "backend/app/research/PREREGISTRATION_OOS.md", symbol: "verdict rules", why: "Replicated, not replicated or underpowered: fixed before the run." },
      { path: "backend/app/insiders/study.py", symbol: "apply_significance", why: "The insider study makes the clustered t part of its significance rule." },
    ],
    readings: [READINGS.petersen2009],
  },
  {
    slug: "survivorship-bias",
    title: "Survivorship bias example: the companies that vanish from your data",
    description:
      "Delisted small caps lose their ticker and price history, so they drop out of backtests. Simulate how much that flatters results and see QuantDesk's real coverage gaps.",
    level: "Beginner",
    minutes: 8,
    concepts: ["survivorship bias", "delisting", "coverage", "point-in-time universe"],
    repoRefs: [
      { path: ES, symbol: "collect (coverage)", why: "Counts companies with no ticker now or no price data; run_design returns them as coverage." },
      { path: ES, symbol: "caveats", why: "The survivorship warning written into every study file." },
      { path: "backend/app/backtest/universe.py", symbol: "build_universe", why: "Every priced offering by a nano cap in the period, with no_ticker and offerings_without_ticker counts." },
      { path: "backend/app/backtest/engine.py", symbol: "StrategyConfig.delist_penalty", why: "The backtest never books a delisting as a gain for a short." },
    ],
    readings: [READINGS.loughranRitter1995],
  },
  {
    slug: "sharpe-dsr-backtest-pitfalls",
    title: "Deflated Sharpe ratio calculator and other backtest pitfalls",
    description:
      "A PSR and deflated Sharpe ratio calculator pre-filled from QuantDesk's backtest, plus the friction waterfall from gross edge to net loss, look-ahead and borrow.",
    level: "Advanced",
    minutes: 15,
    concepts: ["Sharpe ratio", "PSR", "deflated Sharpe ratio", "frictions", "in-sample vs out-of-sample", "look-ahead bias", "borrow cost"],
    repoRefs: [
      { path: "backend/app/backtest/stats.py", symbol: "psr", why: "Probabilistic Sharpe Ratio from sample length, skew and kurtosis." },
      { path: "backend/app/backtest/stats.py", symbol: "expected_max_sharpe, dsr", why: "The luck benchmark for N trials and the Sharpe deflated against it." },
      { path: "backend/app/backtest/engine.py", symbol: "simulate", why: "The daily loop: borrow charged daily, stops, recalls, delistings, liquidity filters." },
      { path: "backend/app/backtest/report.py", symbol: "waterfall", why: "Adds one real-world friction at a time, from frictionless to the base case." },
      { path: "backend/app/backtest/report.py", symbol: "readiness", why: "Gates such as Deflated Sharpe (A) >= 0.95 decide the verdict." },
    ],
    readings: [READINGS.baileyLdp2012, READINGS.baileyLdp2014, READINGS.harveyLiuZhu2016],
  },
];

export const LESSON_SLUGS = LESSONS.map((l) => l.slug);

export function getLesson(slug: string): Lesson | undefined {
  return LESSONS.find((l) => l.slug === slug);
}

/** Date the lesson text was last revised (bump when the prose changes): datePublished / dateModified floor. */
export const LESSONS_REVISED = "2026-10-19";

export const lessonPath = (slug: string) => `/learn/${slug}`;
export const CURRICULUM_PATH = "/learn/curriculum";

/**
 * Optional NEXT_PUBLIC_REPO_URL (e.g. https://github.com/owner/repo): repo references become links to
 * `${REPO_URL}/blob/main/${path}`. Without it they render as plain <code> paths. Inlined at build time.
 */
export const REPO_URL = (process.env.NEXT_PUBLIC_REPO_URL ?? "").replace(/\/+$/, "");

export function repoHref(path: string): string | null {
  return REPO_URL ? `${REPO_URL}/blob/main/${path}` : null;
}

/** Title used in <title> and Open Graph. */
export const lessonDocTitle = (l: Lesson) => `${l.title} · QuantDesk Learn`;
