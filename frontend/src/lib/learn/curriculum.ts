// 8-week self-study path for /learn/curriculum. Plain data. Every path exists in this repo.
// Exercises change code in a throwaway branch and run the backend tests with scripts/pytest.sh
// (mounts the current source into the test image; no rebuild needed).

import { READINGS, type Reading, type RepoRef } from "./lessons";

export interface Week {
  week: number;
  title: string;
  goal: string;
  concepts: string[];
  /** Lesson slugs that cover this week. */
  lessons: string[];
  read: RepoRef[];
  exercise: { task: string; command: string; lookFor: string };
  readings: Reading[];
}

const ES = "backend/app/research/eventstudy.py";

export const CURRICULUM: Week[] = [
  {
    week: 1,
    title: "Filings as events, and when day 0 is",
    goal: "Know what counts as an event and which close a trader could first act on.",
    concepts: ["SEC forms and 8-K items", "signal taxonomy", "acceptance time", "15:30 ET cut-off"],
    lessons: ["event-study"],
    read: [
      { path: "backend/app/pipeline/signals.py", symbol: "signals_for_filing", why: "Form + items to signals." },
      { path: ES, symbol: "day0_index", why: "The timing rule." },
    ],
    exercise: {
      task: "Write a test for day0_index: a filing accepted at 15:29 ET maps to that day's close, one at 15:30 ET to the next trading day, and one before a 6-day gap in prices returns None.",
      command: "bash scripts/pytest.sh tests/test_eventstudy.py",
      lookFor: "Your new test passes; then move the cut-off to 16:00 in a branch and watch which existing tests fail.",
    },
    readings: [READINGS.mackinlay1997],
  },
  {
    week: 2,
    title: "Abnormal returns, horizons and costs",
    goal: "Compute a market-adjusted drift by hand and see where costs and borrow enter.",
    concepts: ["stock minus benchmark", "reaction vs drift", "round-trip costs", "borrow APR"],
    lessons: ["event-study"],
    read: [
      { path: ES, symbol: "measure, bench_ret", why: "Reaction and drift per event." },
      { path: ES, symbol: "HORIZONS, COSTS, BORROW_APR", why: "The fixed design constants." },
    ],
    exercise: {
      task: "In a branch, add a 10-day horizon (HORIZONS = [5, 10, 20]) and see which tests fail. Each failure is a place that assumed the old grid: the test suite documents the design.",
      command: "bash scripts/pytest.sh tests/test_eventstudy.py tests/test_oos.py",
      lookFor: "Failures in tests that pin the horizon grid and the pre-registered design. Do not merge: a new horizon is a new design.",
    },
    readings: [READINGS.mackinlay1997, READINGS.loughranRitter1995],
  },
  {
    week: 3,
    title: "Baselines: compared with what?",
    goal: "Separate 'small caps drift down' from 'this filing makes them drift down'.",
    concepts: ["ordinary-day baseline", "excess return", "Welch t"],
    lessons: ["baselines"],
    read: [
      { path: ES, symbol: "baseline_events", why: "Pseudo-events every 21 trading days." },
      { path: ES, symbol: "welch_t", why: "Event vs baseline test." },
    ],
    exercise: {
      task: "Write a test for welch_t with two hand-made samples whose means differ by a known amount; check the sign, and that it returns 0 when either side has fewer than 2 values.",
      command: "bash scripts/pytest.sh tests/test_eventstudy.py",
      lookFor: "The value matches a hand calculation to 1e-9.",
    },
    readings: [READINGS.mackinlay1997],
  },
  {
    week: 4,
    title: "Multiple testing",
    goal: "Explain why |t| = 2 means little when 100 tests were run.",
    concepts: ["false discovery", "Bonferroni", "data snooping"],
    lessons: ["multiple-testing"],
    read: [{ path: ES, symbol: "summarize", why: "Where t_crit comes from." }],
    exercise: {
      task: "Write a test that feeds summarize() pure-noise measurements from a seeded random.Random for many signals and asserts that no row is `significant`, while a few are `nominal_significant`.",
      command: "bash scripts/pytest.sh tests/test_eventstudy.py",
      lookFor: "Roughly 5% nominal hits, zero significant ones. Change the seed and check it still holds.",
    },
    readings: [READINGS.harveyLiuZhu2016],
  },
  {
    week: 5,
    title: "Dependence and clustered standard errors",
    goal: "Know when events are not independent and what the clustered t fixes.",
    concepts: ["cluster-robust SE (CR1)", "effective sample size", "firm effects"],
    lessons: ["clustered-errors"],
    read: [
      { path: ES, symbol: "clustered_se, clustered_t, clustered_welch_t", why: "The CR1 estimator." },
    ],
    exercise: {
      task: "Write a test for clustered_t: with one observation per cluster it equals t_stat; with every value duplicated within its own cluster the plain t grows by about sqrt(2) while the clustered t does not.",
      command: "bash scripts/pytest.sh tests/test_eventstudy.py",
      lookFor: "Both properties hold; then break the G/(G-1) factor in a branch and see your test catch it.",
    },
    readings: [READINGS.petersen2009],
  },
  {
    week: 6,
    title: "Pre-registration and out-of-sample replication",
    goal: "Run a confirmatory test whose rules were fixed before the data was seen.",
    concepts: ["pre-registration", "confirmatory vs exploratory", "fresh companies", "verdict rules"],
    lessons: ["clustered-errors", "multiple-testing"],
    read: [
      { path: "backend/app/research/PREREGISTRATION_OOS.md", symbol: "sections 2-5", why: "The fixed design." },
      { path: "backend/app/research/oos.py", symbol: "HYPOTHESES, confirmatory", why: "The code that implements it." },
      { path: "backend/tests/test_oos.py", symbol: "MIN_COMPANIES / PREREGISTRATION asserts", why: "The guard that code and file match." },
    ],
    exercise: {
      task: "In a branch, change MIN_COMPANIES in oos.py from 15 to 10 and run the OOS tests. The failure is the point: the test suite refuses a silent design change.",
      command: "bash scripts/pytest.sh tests/test_oos.py",
      lookFor: "A failing assertion on (MIN_COMPANIES, MIN_N) == (15, 20): code and pre-registration must match.",
    },
    readings: [READINGS.harveyLiuZhu2016, READINGS.loughranRitter1995],
  },
  {
    week: 7,
    title: "Insider purchases: parsing Form 4",
    goal: "Turn raw SEC ownership XML into clean, safe transaction rows.",
    concepts: ["Form 4", "open-market purchase (code P)", "opportunistic vs routine insiders", "safe XML parsing"],
    lessons: ["clustered-errors"],
    read: [
      { path: "backend/app/insiders/form4.py", symbol: "parse_ownership_xml", why: "Namespace stripping, DOCTYPE/ENTITY rejection, price sanity." },
      { path: "backend/app/insiders/classify.py", symbol: "classify_trades", why: "Opportunistic vs routine, after Cohen, Malloy & Pomorski." },
      { path: "backend/tests/fixtures/form4/form4_two_purchases.xml", symbol: "fixture", why: "A real-shaped filing to parse." },
    ],
    exercise: {
      task: "Parse a Form 4 fixture: write a test that loads form4_sparse_grant.xml with parse_ownership_xml and asserts that none of its transactions has code \"P\" (open-market purchase), then copy form4_two_purchases.xml into a new fixture with a third purchase block and assert three transactions come back.",
      command: "bash scripts/pytest.sh tests/test_insiders.py",
      lookFor: "Grants and empty values are tolerated but never counted as purchases.",
    },
    readings: [READINGS.lakonishokLee2001, READINGS.cohenMalloyPomorski2012],
  },
  {
    week: 8,
    title: "Backtests, frictions and the deflated Sharpe ratio",
    goal: "Read a backtest the way a skeptic would: frictions, trials and out-of-sample first.",
    concepts: ["friction waterfall", "borrow and recalls", "PSR", "DSR", "MinTRL", "tamper-evident track record"],
    lessons: ["sharpe-dsr-backtest-pitfalls", "survivorship-bias"],
    read: [
      { path: "backend/app/backtest/stats.py", symbol: "psr, expected_max_sharpe, dsr, min_trl", why: "Overfitting-aware statistics." },
      { path: "backend/app/backtest/report.py", symbol: "waterfall, borrow_sensitivity, readiness", why: "Where the edge goes, and the gates." },
      { path: "backend/app/journal/digest.py", symbol: "day_hash, verify_chain", why: "How the live track record is sealed." },
    ],
    exercise: {
      task: "Write a test that dsr() falls as the number of trial Sharpes grows for the same daily returns, and that psr() with skew 0 and kurtosis 3 matches the textbook normal formula.",
      command: "bash scripts/pytest.sh tests/test_backtest.py tests/test_journal_digest.py",
      lookFor: "More trials, lower DSR: every variant you try raises the bar.",
    },
    readings: [READINGS.baileyLdp2012, READINGS.baileyLdp2014],
  },
];
