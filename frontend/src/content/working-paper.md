# Do SEC filing events predict small-cap returns? Evidence from an in-sample event study, a pre-registered out-of-sample replication, and Form 4 insider purchases

*Afterfile working paper, October 2026. Research and education only. Every return in this paper is a historical, market-adjusted average or a hypothetical simulation. Nothing here is investment advice, and no result describes a strategy that has been traded.*

## Abstract

We ask whether SEC filing events predict the subsequent returns of small US companies once day 0 is timed to the EDGAR acceptance timestamp, returns are adjusted for the market and for the same firms' ordinary-day drift, and results are judged net of trading costs and short-borrow fees. In an in-sample event study of 750 randomly drawn operating companies (October 2023 to August 2026, 21,842 measured events, 102 tests), only one signal survives a Bonferroni correction (|t| ≥ 3.49): nano-cap companies that price an offering drift -15.63% against the Russell 2000 ETF over the next 20 trading days (n = 302, t = -6.67), which is -13.67% relative to the same firms on ordinary days, and a hypothetical +8.66% per event after assumed costs and borrow. A pre-registered replication on an earlier period (October 2020 to August 2023) with companies the first study never sampled (21,223 measured events) does not confirm it: the nano-cap offering drift is still negative and distinct from zero under firm-clustered errors (t = -2.64 against a confirmatory critical value of 2.394), but its mean net of costs and borrow is -0.06%, so the pre-registered verdict is "not replicated". The other two pre-registered leads fail outright. A portfolio backtest of the offering short with realistic frictions loses -33.36% in the out-of-sample period. In a separate pre-registered study of Form 4 open-market purchases by directors and officers, micro-cap cluster purchases are the one cell that passes: +1.66% excess over ordinary days within five trading days (n = 662, 177 firms, clustered t = 3.29), but only +0.11% per event after a 1.5% round-trip cost.

## 1 Introduction

Public companies disclose material events to the SEC within days, and those filings are free, machine-readable and timestamped to the second. For the smallest listed companies, which have little analyst coverage and thin trading, prices may adjust slowly, and the literature on seasoned equity offerings and insider trading suggests where to look (Loughran and Ritter, 1995; Seyhun, 1986; Lakonishok and Lee, 2001; Cohen, Malloy and Pomorski, 2012).

The practical question is narrower. A drift that is statistically significant but disappears after the bid-ask spread, the cost of borrowing a hard-to-borrow stock and the timing limits of a real order is a fact about prices, not an opportunity. A drift found in one period of a broad search may be one of many patterns that search was bound to find (Harvey, Liu and Zhu, 2016). We therefore use three safeguards. Every cell of the in-sample grid is tested under a Bonferroni correction and must beat both zero and the same firms' ordinary-day drift, in a direction fixed in advance, net of costs. The leads from that grid were written into a dated pre-registration with a fixed critical value and mechanical verdicts before any out-of-sample data were collected. The insider study was pre-registered separately with its own test family.

The answer is mostly negative. The one strong in-sample result recurs gross of costs in an earlier period but does not survive costs and borrow there, and a backtest with plausible frictions loses money in both periods. The insider result is the only pre-registered pass, and it is economically thin.

## 2 Data

**Filings.** Events are non-amended filings with their acceptance timestamps from the SEC EDGAR submissions API for each sampled company, mapped to signals by the taxonomy that drives Afterfile's live alerts (for example 8-K item 1.01 material agreements, item 3.02 unregistered equity sales, and 424B4/424B5 final prospectuses for priced offerings). Signals and their expected directions were fixed before results were computed.

**Size.** Companies are bucketed by SEC public float from the XBRL frame for the second calendar quarter before each window (CY2023Q2 for the in-sample and insider studies, CY2020Q2 for the replication), frozen so that bucket assignment uses no later information: nano (under $50M), micro ($50M to $300M), small ($300M to $2B) and large (over $10B, a control). Each study draws a random sample of operating companies per bucket, excluding SPACs (SIC 6770) and entities without a ticker.

**Insider transactions.** The insider study uses the SEC Insider Transactions Data Sets (quarterly flattened Forms 3, 4 and 5) for 2020Q1 to 2026Q2. A qualifying purchase is a non-amended Form 4 open-market purchase (code P) by a director or officer, with positive shares and price, not flagged as a Rule 10b5-1 plan trade. Purchases are aggregated per issuer and filing date, and an issuer-day with at least $10,000 of purchases is an event. A random 50 events were cross-checked against the raw Form 4 XML, with a 100% match rate.

**Prices.** Daily split- and dividend-adjusted closes come from the Yahoo Finance chart API, an unofficial source whose terms restrict commercial use. They are used for personal, local research only: cached locally, never committed, redistributed or served, with only aggregate statistics published. Any public use would require a licensed feed.

**Samples and coverage.**

| Study | Window | Companies (nano / micro / small / large) | Measured events | Tests |
|---|---|---|---|---|
| In-sample | 2023-10-01 to 2026-08-31 | 150 / 250 / 250 / 100 | 21,842 | 102 |
| Out-of-sample (pre-registered) | 2020-10-01 to 2023-08-31 | 150 / 250 / 250 / 100 | 21,223 | 102 exploratory, 3 confirmatory |
| Insider purchases (pre-registered) | 2023-10-01 to 2026-06-30 | 300 / 400 / 400 / 100 | 6,336 | 32 |

Coverage losses indicate survivorship. In the in-sample draw, 51 nano, 67 micro, 50 small and 5 large candidates had no ticker and were replaced by the oversampling rule; in the replication, which reaches further back, the counts were 161, 298, 165 and 21.

## 3 Design

**Day 0.** For filings, day 0 comes from the EDGAR acceptance time in US Eastern time. A filing accepted before 15:30 ET is assigned that session's close; one accepted at or after 15:30 ET, including after the close, moves to the next session's close. Events with no price bar within five days are dropped. The insider data sets record a filing date but no acceptance time, so the insider study's day 0 is conservatively the first close after the filing date.

**Returns.** Drift at horizon h (5 and 20 trading days) runs from the day-0 close to the close h days later. Abnormal drift is the stock's return minus the benchmark's over the same dates: IWM for nano, micro and small companies, SPY for large ones.

**Ordinary-day baseline.** For each sampled company we take an ordinary observation every 21 trading days and measure it the same way. Each cell reports its excess over its bucket's baseline mean and a Welch t-statistic against the baseline. This matters: in-sample nano caps drifted -1.96% over 20 days on ordinary days, about an eighth of the raw offering drift.

**Direction, costs and borrow.** Each signal's prior direction was fixed before results: negative signals are measured as shorts, positive and ambiguous ones as longs. Net returns deduct a round-trip cost per bucket (nano 3%, micro 1.5%, small 0.5%, large 0.1%); shorts also pay annual borrow per bucket (nano 50%, micro 25%, small 5%, large 0.5%) pro-rated over the holding period. These are assumptions, not measurements.

**Outliers and sample size.** Drift is winsorized at the 1st and 99th percentiles within each bucket. Cells with fewer than 20 events are not tested.

**Multiple testing.** The critical value is Bonferroni over every (signal, bucket, horizon) cell in a study, two-sided at 5%: the normal quantile at 1 - 0.05 / (2 × number of tests), which is 3.49 for the 102-cell filing grid and 3.16 for the 32 insider cells. A cell is significant only if the t-statistics against zero and against the baseline both clear it, the mean and excess point the prior's way, and the mean net of costs is positive.

**Clustered errors.** Events from one company are not independent, and serial issuers file many offerings. We compute firm-clustered (CR1) standard errors with companies as clusters (Petersen, 2009; Cameron and Miller, 2015). In-sample they are reported only. The replication's confirmatory test and the insider rule use the clustered t against zero; the replication also clusters the baseline comparison, ignoring the covariance between event and baseline samples that share companies.

**Pre-registration.** The in-sample grid produced one significant cell and several leads that failed the full rule. Rather than adjust the design, we wrote the leads into a pre-registration dated 2026-10-19, committed before any out-of-sample run existed. It fixes the window, size frame and seed, excludes every company that was a candidate in the in-sample draw, and defines a confirmatory family of three hypotheses, all at 20 days and measured as shorts: H1, offerings priced (424B4/424B5) in nano caps; H2, unregistered share sales (8-K item 3.02) in micro and nano caps pooled; H3, material agreements (8-K item 1.01) in nano caps. The confirmatory critical value is Bonferroni over three hypotheses, 2.394. Verdicts are mechanical: "underpowered" with fewer than 20 events or 15 companies; otherwise "replicated" only if both clustered t-statistics clear 2.394, the mean and excess are negative and the mean net of costs and borrow is positive; otherwise "not replicated". The insider study was pre-registered on the same date with its own universe, signals, a Cohen, Malloy and Pomorski (2012) style split of insiders into routine and opportunistic traders, and its own Bonferroni family.

## 4 Results

### 4.1 In-sample event study

Of 102 tested cells, two pass the full rule, both nano-cap priced offerings. Table 1 shows them with the leads later pre-registered. Cost includes borrow for shorts (for nano offerings at 20 days, 3.97% of the 6.97%); net is the hypothetical mean per event after both.

**Table 1. In-sample (2023-10 to 2026-08), selected cells.**

| Signal | Bucket | Horizon | n | Firms | Mean abnormal | t | Excess vs baseline | t vs baseline | Cost | Net (hypothetical) | Significant |
|---|---|---|---|---|---|---|---|---|---|---|---|
| offering_priced | nano | 5d | 302 | 74 | -6.97% | -5.69 | -6.52% | -5.21 | +3.99% | +2.97% | yes |
| offering_priced | nano | 20d | 302 | 74 | -15.63% | -6.67 | -13.67% | -5.71 | +6.97% | +8.66% | yes |
| offering_priced | micro | 20d | 356 | 99 | -3.09% | -2.37 | -2.51% | -1.90 | +3.48% | -0.40% | no |
| unregistered_equity | nano | 20d | 410 | 102 | -8.76% | -3.98 | -6.80% | -3.01 | +6.97% | +1.79% | no |
| unregistered_equity | micro | 20d | 312 | 107 | -5.96% | -3.75 | -5.38% | -3.36 | +3.48% | +2.48% | no |
| material_agreement | nano | 20d | 1025 | 129 | -7.43% | -5.65 | -5.47% | -3.89 | +3.00% | -10.44% | no |

The nano-cap offering drift deepens from 5 to 20 days, and 74 distinct companies contribute its 302 events. Unregistered share sales show negative drift with t-statistics beyond 3.49 against zero but not against the baseline. Material agreements have an ambiguous prior and were measured long, so their negative drift yields a large negative net and the rule rejects them. These three patterns became H1 to H3.

### 4.2 Pre-registered out-of-sample replication

Table 2 reports the confirmatory block exactly as the pre-registered code produced it.

**Table 2. Confirmatory tests (2020-10 to 2023-08, fresh companies, 20 days, short), critical value 2.394.**

| Hypothesis | Signal | Buckets | n | Firms | Mean abnormal | Excess vs baseline | Clustered t | Clustered t vs baseline | Net (hypothetical) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | offering_priced | nano | 228 | 69 | -6.91% | -7.57% | -2.64 | -2.84 | -0.06% | not replicated |
| H2 | unregistered_equity | micro + nano | 719 | 182 | -1.14% | -1.30% | -0.76 | -0.86 | -4.38% | not replicated |
| H3 | material_agreement | nano | 966 | 136 | -1.51% | -2.17% | -0.93 | -1.28 | -5.46% | not replicated |

H1 is the instructive case. The drift after nano-cap offerings recurs in an independent period and sample: -7.57% relative to ordinary days, with clustered t = -2.64 against zero and -2.84 against the baseline, both beyond 2.394 and both the registered way. It fails on one condition: after 3% round-trip costs and 20 days of borrow at 50% a year, the mean net is -0.06%. The effect is about half its in-sample size, which does not pay for the frictions. The registered verdict is "not replicated". H2 (t = -0.76) and H3 (t = -0.93) show no reliable drift.

The exploratory grid, judged with the original 102-cell correction, flags one cell the in-sample study did not: micro-cap offerings (Table 3). In-sample that cell had t = -2.37 and a negative net, so it is a lead for a future pre-registered test, not a confirmation, and it has not been backtested.

**Table 3. Exploratory replication grid, micro-cap priced offerings.**

| Horizon | n | Firms | Mean abnormal | t | Clustered t | Excess vs baseline | t vs baseline | Net (hypothetical) |
|---|---|---|---|---|---|---|---|---|
| 5d | 397 | 106 | -2.33% | -3.92 | -2.95 | -2.62% | -4.36 | +0.33% |
| 20d | 397 | 106 | -5.71% | -5.34 | -3.97 | -5.57% | -5.12 | +2.23% |

The baseline also changed sign: out of sample, nano caps drifted +0.66% over 20 days on ordinary days, against -1.96% in-sample, a reminder that one period's market shapes what "abnormal" means.

### 4.3 Form 4 insider purchases

The insider study tests 32 cells (critical value 3.16) across four signals: all qualifying purchases, cluster purchases (a second distinct director or officer buying within ten calendar days), and purchases by insiders classified as opportunistic or routine. Table 4 shows selected cells; the t against zero is firm-clustered and the t vs baseline is the Welch statistic the registered rule uses.

**Table 4. Insider purchases (filing dates 2023-10 to 2026-06, long), selected cells.**

| Signal | Bucket | Horizon | n | Firms | Mean abnormal | Excess vs baseline | Clustered t | t vs baseline | Net (hypothetical) | Significant |
|---|---|---|---|---|---|---|---|---|---|---|
| insider_cluster_purchase | nano | 5d | 266 | 75 | +1.51% | +1.87% | 1.32 | 1.87 | -1.49% | no |
| insider_cluster_purchase | micro | 5d | 662 | 177 | +1.61% | +1.66% | 3.29 | 4.35 | +0.11% | yes |
| insider_cluster_purchase | micro | 20d | 662 | 177 | +2.44% | +2.42% | 2.27 | 3.52 | +0.94% | no |
| insider_purchase | micro | 5d | 1708 | 266 | +1.20% | +1.25% | 4.06 | 5.20 | -0.30% | no |
| insider_purchase | small | 20d | 1321 | 267 | +1.17% | +1.08% | 2.19 | 2.90 | +0.67% | no |

Exactly one cell passes: micro-cap cluster purchases over five trading days, with +1.66% excess over ordinary days (n = 662, 177 firms), clustered t = 3.29 against zero and a Welch t of 4.35 against the baseline. The economic margin is small: after the 1.5% micro-cap round trip, the hypothetical mean is +0.11% per event, and only 38.7% of events have positive abnormal drift. All micro-cap purchases show a stronger statistical signal (clustered t 4.06) but a mean net of -0.30% at five days, so they fail on costs. Twenty-day effects are larger in level, but their clustered t-statistics fall short of 3.16. In nano caps, with a 3% round trip, no insider cell clears costs.

The registered descriptive expectation that opportunistic insiders' purchases precede larger drift than routine insiders' holds in six of eight bucket-horizon comparisons, including micro caps at 20 days (+2.73% against -0.91%, a difference of +3.65%), and fails in small caps at both horizons. It was registered as descriptive, not as a significance test.

## 5 Backtest and frictions

An event-study mean assumes every event trades at the day-0 close at the assumed cost. To test the nano-cap offering result under realistic conditions, we simulated a hypothetical daily portfolio over every priced offering by a sub-$50M-float company in two periods: October 2020 to August 2023 (out of sample for this signal) and October 2023 to August 2026 (discovery). The simulation enters one close after day 0, because the short-sale price test (Rule 201) often blocks shorting into the first drop; requires a $1 price and $200,000 median daily dollar volume; sizes positions at 3% of $100,000 starting equity, capped by volume; hedges with IWM; charges a 3% round trip and 75% annual borrow; treats 30% of names as unborrowable; applies a 2% daily recall chance and a +40% squeeze stop filled 5% worse; and gives no credit for delistings.

**Table 5. Hypothetical backtest, base configuration.**

| Period | Role | Signals | Trades | Total return | Sharpe | Max drawdown |
|---|---|---|---|---|---|---|
| Oct 2020 to Aug 2023 | out of sample | 812 | 231 | -33.36% | -1.24 | 38.96% |
| Oct 2023 to Aug 2026 | discovery | 1,699 | 412 | -11.45% | -0.24 | 32.94% |

The friction waterfall locates the loss. Out of sample, the average gross trade at the day-0 close returned +4.65% across 561 signals; tradable names after the 3% spread and slippage returned +2.11%; the 75% borrow fee turned that into -3.67%; and stops, recalls and unborrowable names took it to -5.55%. In the discovery period the gross average was +8.15%, +0.07% after borrow and -0.72% after all frictions. The out-of-sample period loses money even with free borrow, and the discovery period breaks even at an average borrow fee of about 75.8% a year.

Borrow is the least certain input. One day of the Interactive Brokers shortable-stocks file for 149 nano-cap issuers that priced an offering in the last six months of the discovery period showed 97.3% borrowable at a median fee of 7.45% a year (36.14% at the 75th percentile). Fees at the moment of an offering are likely higher, so this is a lower bound, and one day is not a borrow model. Cheaper borrow alone does not rescue the out-of-sample period, which fails at zero borrow. Across 14 configurations tried, the deflated Sharpe ratio (Bailey and López de Prado, 2014) for the out-of-sample period is 0, and the strategy fails 8 research readiness gates, including the worst-case stress test (Sharpe -4.30 with doubled costs, 300% borrow, half the names unborrowable and a two-day delay).

## 6 Limitations

**Survivorship.** Delisted companies lose their ticker or price history and drop out, more so the further back the window goes. Missing names skew toward poor outcomes, so negative drift is probably understated, but they are also the hardest names to borrow and trade.

**Borrow availability and cost.** The event study uses a flat borrow rate per bucket and the backtest a flat 75% with random unavailability. Real fees for hard-to-borrow small caps vary daily, can be far higher right after an offering, or shares may be unavailable. A forward borrow archive has only just begun.

**Price data quality and licensing.** Yahoo adjusted closes come from an unofficial endpoint without service guarantees, under terms that restrict commercial use. Corporate-action adjustments in tiny companies can be wrong, and the data cannot be redistributed. These results are personal research; replication with a licensed feed is needed before any public use.

**A single period per study.** Each window is under three years. The in-sample and replication periods differ visibly in their ordinary-day baselines, and the offering effect looks strongest in recent years, which could be a change in the issuer population or luck.

**Serial issuers and non-independence.** Some companies file repeatedly, and events in the same week share market shocks. Clustered errors address within-company correlation but not same-date correlation across companies, so t-statistics remain somewhat overstated.

**Beta and factors.** Abnormal returns are stock minus index, with no estimated beta and no size, value or momentum adjustment (MacKinlay, 1997). Small, distressed issuers may have exposures that differ from IWM's.

**Execution.** Fills at the close are assumed. Real fills in illiquid names are worse, which also makes the insider study's net figures optimistic.

## 7 Conclusion

The evidence that SEC filing events predict small-cap returns in a usable way is weak. The only filing signal that passed a strict in-sample test, the negative drift after nano-cap priced offerings, recurs gross of costs in an independent earlier period, but it is not tradable net of costs and borrow: in the pre-registered replication its mean net of costs and borrow is -0.06% and the verdict is "not replicated", and a hypothetical backtest with realistic frictions loses -33.36% out of sample (Sharpe -1.24). The other pre-registered leads show no reliable effect. The one pre-registered pass comes from Form 4 data: micro-cap insider cluster purchases are followed by +1.66% excess drift over ordinary days within five trading days (n = 662, 177 firms, clustered t = 3.29), significant under the pre-registered rule but thin after costs, with a hypothetical mean net of about +0.11% per event, smaller than plausible errors in the cost assumption. Natural next steps are a fresh pre-registered replication of the insider cluster result, a pre-registered test of the micro-cap offering lead, and measured rather than assumed borrow costs. All results here are historical and hypothetical, and none is a recommendation to trade.

## Appendix A: Reproducibility

Python runs inside the project's Docker image; published result files are in `docs/results/`.

- `make reproduce` (`bash scripts/reproduce.sh main`) replays the in-sample study offline from cached inputs and compares it with the newest `docs/results/event_study_*.json`, printing IDENTICAL or DIFF.
- `make reproduce-oos` (`bash scripts/reproduce.sh oos`) replays the pre-registered replication offline and prints its confirmatory verdicts.
- `make reproduce-insiders` (`bash scripts/reproduce.sh insiders`) replays the Form 4 insider study offline.
- Online runs: `docker compose run --rm api python -m app.research.eventstudy`, `docker compose run --rm api python -m app.research.oos`, `docker compose run --rm api python -m app.insiders.study` and `docker compose run --rm api python -m app.backtest.report`.
- Each study run writes a hash-only input manifest under the data volume's `snapshots/` folder; no cached price data is committed.
- Pre-registrations: `backend/app/research/PREREGISTRATION_OOS.md` and `backend/app/insiders/PREREGISTRATION.md`.
- Headline numbers are checked against the result files by `backend/app/research/paper_numbers.py` (test: `backend/tests/test_paper_numbers.py`).

Result files: `docs/results/event_study_2026-10-15.json` (in-sample), `docs/results/event_study_oos_2026-10-19.json` (replication), `docs/results/event_study_insider_purchases_2026-10-19.json` (insider purchases), `docs/results/backtest_2026-10-16.json` (backtest).

## References

- Bailey, D. H., and López de Prado, M. (2014). The deflated Sharpe ratio: correcting for selection bias, backtest overfitting, and non-normality. *Journal of Portfolio Management*.
- Cameron, A. C., and Miller, D. L. (2015). A practitioner's guide to cluster-robust inference. *Journal of Human Resources*.
- Cohen, L., Malloy, C., and Pomorski, L. (2012). Decoding inside information. *Journal of Finance*.
- Harvey, C. R., Liu, Y., and Zhu, H. (2016). ... and the cross-section of expected returns. *Review of Financial Studies*.
- Lakonishok, J., and Lee, I. (2001). Are insider trades informative? *Review of Financial Studies*.
- Loughran, T., and Ritter, J. R. (1995). The new issues puzzle. *Journal of Finance*.
- MacKinlay, A. C. (1997). Event studies in economics and finance. *Journal of Economic Literature*.
- Petersen, M. A. (2009). Estimating standard errors in finance panel data sets: comparing approaches. *Review of Financial Studies*.
- Seyhun, H. N. (1986). Insiders' profits, costs of trading, and market efficiency. *Journal of Financial Economics*.
