# backend/app/fundamentals: dilution history and cash runway

Per-company numbers small-cap traders check first. Everything is computed from free SEC data,
cached for 24 h under `data/companyfacts/` and `data/submissions_live/`.

## `service.company_profile(cik, data_dir, user_agent)`

| Output | Source | Method |
|---|---|---|
| `cash` | XBRL `CashAndCashEquivalentsAtCarryingValue` (fallback: the restricted-cash-inclusive tag) | Latest `end` date; later `filed` wins ties |
| `operating_cash_flow` | XBRL `NetCashProvidedByUsedInOperatingActivities` | **TTM = last fiscal year + current YTD − prior-year same-length YTD** (10-Q cash flows are year-to-date). Falls back to the fiscal year when the matching YTD pair is missing. |
| `runway` | cash ÷ (−TTM / 12) | `burning` with months and a run-out date, `cash_flow_positive`, or `unknown`. As of the cash date, before any later raise. |
| `share_change_1y` | dei `EntityCommonStockSharesOutstanding` (10-K/10-Q cover pages) | Latest value vs the one closest to 365 days earlier; needs ≥ 180 days apart |
| `dilution_filings` | submissions JSON | 424B1–5, S-1, S-3, F-1, F-3, and 8-K with item 3.02 (unregistered sale), last 3 years, no amendments |
| `raises_since_cash_date` | the same list | 424Bs filed after the cash date, which extend the runway |

All functions except `company_profile` are pure and tested in `tests/test_fundamentals.py`.

## Caveats

- XBRL tags vary by company. When neither cash tag exists, the panel says "not reported"; we don't guess.
- Banks, REITs and foreign filers (20-F) often lack these tags or don't burn cash in the same sense.
- The runway is arithmetic on reported numbers, not a forecast. The UI says so.

## API / UI

- `GET /api/tickers/{symbol}/fundamentals`: 404 for an unknown ticker, 502 if SEC is unreachable.
- `frontend/src/components/DilutionPanel.tsx`, on `/ticker/[symbol]`.

## Next

- Short interest: FINRA twice-monthly files.
- Halts: Nasdaq trade-halt RSS.
- Reverse-split history: 8-K item 5.03 plus Yahoo split events.
