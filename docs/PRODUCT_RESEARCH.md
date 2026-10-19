> **Decision 2026-10-19: local-only, no paid tier.** QuantDesk runs on the owner's machine via Docker. No Stripe, accounts, pricing or hosting; the monetization sections below are kept as background research only.

# QuantDesk: Product Research (Small-Cap Event Intelligence)

*Compiled 2026-10-16. Educational research, not legal or financial advice. Prices were checked against vendor pages where those pages loaded. **(secondary)** means the figure came from a third-party review or aggregator and was not confirmed on the vendor's own page. Several vendor pages (DilutionTracker, Fintel, Benzinga, TipRanks) blocked automated fetches, so their prices are secondary and should be re-checked by hand before you quote them.*

## TL;DR

- **The market is real and crowded at the "dilution data" layer.** DilutionTracker is the default small-cap dilution tool, and brokers like CenterPoint/Clear Street give it away free to active clients. AskEdgar ($59 to $199/mo) is the AI-filings player. A wave of newer clones (DilutionWatch, Dilutracker) compete on price.
- **QuantDesk's gap is "what happens next", not "what was filed".** No competitor reviewed here publishes per-signal-type historical reaction statistics (an event study) or a public, timestamped track record of its alerts. QuantDesk also covers non-dilution adverse events: 8-K Item 4.02 restatements, 4.01 auditor changes, 3.01 delisting notices, and 13D activists. That combination is the wedge.
- **Table stakes before anyone pays:** fast alerts (seconds to about a minute after EDGAR acceptance), push, email and Discord delivery, watchlists, and a per-ticker page with dilution history, cash runway, float, short interest and halts.
- **Price point:** the retail band is roughly $25 to $75/mo. Launch at about $29 to $49/mo with a useful free tier (delayed alerts), which mirrors Unusual Whales' delayed-free model.
- **Legal posture:** stay inside the publisher's exclusion. Content must be impersonal, bona fide and regularly published. No personalized advice, no managing money, no auto-trading. Treat the Edge Lab and backtester as hypothetical performance: follow FTC substantiation norms and borrow the SEC Marketing Rule's disclosure discipline voluntarily.
- **Biggest hidden cost is price data licensing.** Yahoo is personal-use only. Displaying prices to paying users needs a license with external-distribution rights. Avoid showing live prices at first and link out instead.

---

## 1. Competitors and adjacent products

### 1.1 Summary table

| Product | What it does | Price (checked 2026-10) | Praise | Complaints / limits |
|---|---|---|---|---|
| **DilutionTracker** | Per-ticker dilution profiles: offering ability, overhead supply, historical dilution, cash need; offering history; shelves, ATMs, warrants, convertibles; pending S-1s; alerts; one-click DAS Trader integration | $74/mo monthly or $49/mo billed annually (secondary, AskEdgar blog); $60 to $74/mo (secondary, DilutionWatch); $60/mo (secondary, RizeTrade). Free via CenterPoint at $100k+ equity or 100k+ monthly shares | "Five-second read" risk dashboard; fast enough for intraday use; the de facto tool for low-float traders | Narrow, dilution only; no charting, scanning or news; limited free tier; data shows structure, not the last hour's events; competitors claim delayed data, roughly 2,300 to 2,500 tickers, and no API, app or AI summaries (all competitor claims, unverified) |
| **AskEdgar** | AI over SEC filings: summaries, dilution and offering data, Nasdaq compliance tracking, screeners, Discord research bots, API | Free (20 AI questions/mo); Pro $59/mo; Professional+ $199/mo; Enterprise custom; 7-day trial | Broad filing coverage, near real time, Discord bots | Seen as pro-oriented and pricier; steeper learning curve (secondary) |
| **BamSEC** (AlphaSense) | Fast filing and transcript reader, table export to Excel, redlines, email filing alerts | Pro $69/mo billed annually; Enterprise via AlphaSense | Analysts love the UI ("very sleek") | Fundamental-analyst tool, not trader alerts; strategic focus shifted after the AlphaSense/Tegus acquisition |
| **Fintel** | Institutional ownership, insider trades, short interest, filings, screener | Not confirmed. Third-party figures conflict: $14.95 to $95/mo (NexusFi), $50 to $100/mo (RizeTrade) | Data breadth in one place; "least expensive" for what it offers | Trustpilot 2.7/5 from 100 reviews (only 3 in the last year): login and billing problems, unresponsive support, refunds refused, doubts about short-interest timeliness |
| **Quiver Quantitative** | Alternative data: congress trades, insiders, lobbying, government contracts; backtesters; alerts | Premium $25/mo or $300/yr (secondary via search of official page); 50% off first-year promos | Free dashboards; congressional data drove growth | Prices and tiers change often with promos |
| **OpenInsider** | Free Form 4 insider screener (cluster buys, filters) | Free | Fast, excellent filters, no paywall | No SLA, no app, no documented API; alerts unclear |
| **Unusual Whales** | Options flow, dark pool, GEX, congress trades, insider data, Discord community | Free (flow delayed 2 days, news 15 min, alerts 30 min); Basic $50/mo ($42 annual); Pro $75/mo ($63 annual); Max $120/mo ($102 annual) | Brand built on congressional-trade tracking; generous free tier | No verified review corpus found (Trustpilot page empty) |
| **WhaleWisdom** | 13F hedge-fund holdings, 13D/G, backtester, API | Free; Standard $90/quarter; Pro $150/quarter; Enterprise custom | Deep 13F history, cheap | 13F data is quarterly and lagged by nature |
| **TipRanks** | Analyst ratings, Smart Score, insider and blogger tracking | Premium about $360 to $420/yr, Ultimate about $600/yr (secondary; official page shows no prices to bots); heavy first-year discounts | Aggregated ratings | Promo-then-list-price renewals (secondary) |
| **Benzinga Pro** | Real-time news, audio squawk, scanner, signals | Basic $37/mo; Streamlined $147/mo; Essential $197/mo, about $166/mo annual (secondary, two sources agree) | News speed "pays for itself" for catalyst traders | Expensive; billing and cancellation complaints on Trustpilot; limited charting |
| **Stocktwits** | Social feed; Edge premium tier | Edge $29.99/mo or $299.99/yr on iOS (secondary, App Store IAP list); $22.95/mo also cited | Large retail audience (distribution channel) | Noise; prices differ by platform |
| **Trade Ideas** | Real-time scanner, alerts; Holly AI signals, backtesting and auto-trading on Premium | Standard $127/mo or $1,068/yr; Premium $254/mo or $2,136/yr (official page) | Powerful scans | Expensive; AI locked behind Premium; Holly accuracy disputed; stability complaints; Trustpilot 3.8 from 46 reviews (secondary) |
| **Finviz Elite** | Screener, real-time quotes, alerts, backtests | $39.50/mo or $299.50/yr; 30-day refund | Free tier is the morning scanner for many traders | No mobile app; charting weaker than dedicated platforms |
| **SEC filing alert tools** | CapEdge/Docoh (email within about a minute), KFilings (free watchlist email), edgar.tools (live stream, SSE on paid tier), PageCrawl, Apify actors (about $0.25/filing or $4 per 1,000 records) | Free to low | Cheap, fast raw alerts | No interpretation, no scoring, no "so what" |
| **Newer dilution clones** | DilutionWatch: scans EDGAR every 60s, AI summaries, DilutionScore. Dilutracker: dilution reports, API, 13F tracker | DilutionWatch Free / $19.95 / $39.95 per month (self-reported); Dilutracker price not listed | Cheaper, more modern | New and unproven; marketing is mostly self-ranked "best of" lists |

### 1.2 How directly does DilutionTracker compete, and where is the gap?

**Overlap (direct):** dilutive offerings are QuantDesk's flagship signal, and DilutionTracker owns that job for small-cap day traders. It is wired into DAS Trader and bundled free by brokers (CenterPoint: $100k+ equity or 100k+ monthly shares), so the core audience often gets it at no cost. Competing head-on with "better dilution profiles" means fighting a free, entrenched incumbent.

**Gap (where QuantDesk can win):**
1. **Outcome statistics.** DilutionTracker tells you a company *can* dilute. It does not show, from what was found, how stocks *historically moved* after a priced offering, an S-1, an auditor change, and so on. The Edge Lab event study is the differentiator. Make it per-signal, per-size bucket (public float), with confidence intervals and sample sizes.
2. **Non-dilution adverse events.** Restatements (8-K Item 4.02), auditor changes (4.01), delisting and compliance notices (3.01), and activist 13Ds are outside DilutionTracker's stated focus. AskEdgar touches Nasdaq compliance, but nobody packages these as one "small-cap distress radar".
3. **Public, timestamped track record.** No competitor reviewed publishes a log of every alert with its subsequent move. That builds trust and doubles as SEO content.
4. **Speed and freshness.** Reviewers note DilutionTracker data "lags" and shows structure rather than the last hour. Seconds-level alerts on EDGAR acceptance are a measurable edge, but DilutionWatch already claims 60-second scans, so speed alone is not a moat.
5. **Positioning.** Be the complement ("open DilutionTracker for the structure, QuantDesk for the alert and the odds"). Price below it and integrate links to it rather than rebuilding every warrant table on day one.

---

## 2. What the product needs to succeed

### 2.1 Must-have features (small-cap traders)

| Feature | Why / evidence | Data source (free where possible) |
|---|---|---|
| **Alerts: push, email, Discord** | Every paid competitor sells real-time alerts; Unusual Whales and AskEdgar gate speed and Discord bots behind paid tiers | Your EDGAR poller to a fan-out queue |
| **Speed after filing** | CapEdge advertises "within a minute"; edgar.tools says "within seconds"; DilutionWatch says 60s scans. Target p50 under 30s and p95 under 60s from EDGAR acceptance, and publish your measured latency | Poll EDGAR's latest-filings feed within the SEC's 10 req/s per-user limit, with a declared User-Agent. The SEC's structured-data RSS only refreshes every 10 minutes, too slow. PDS is the paid dedicated feed if you outgrow polling |
| **Watchlists** | Universal (Unusual Whales caps them by tier; WhaleWisdom caps at 5 free) | Postgres |
| **Per-company dilution history and cash runway** | DilutionTracker's core: offering history, shelf/ATM capacity, warrants, convertibles, "cash need" | XBRL company facts (cash, operating cash burn) plus 424B/S-1/S-3/8-K parsing; runway = cash / quarterly burn |
| **Float and short interest** | Fintel, Finviz and others show it; small-cap traders screen on it | Public float from 10-K cover (already in app); FINRA short interest, free, published twice monthly about 8 business days after settlement |
| **Halts** | Core small-cap catalyst | Nasdaq Trader trade-halt RSS (free; terms say Nasdaq owns the content, don't modify it; cache, don't hammer) |
| **AI summary, but sourced** | AskEdgar's entire pitch; DilutionWatch copies it | Link every claim to the filing section; show the raw excerpt |

### 2.2 Trust

- **Public signal log:** every alert, its EDGAR acceptance timestamp, your alert timestamp, and returns at +1d/+5d/+20d versus a benchmark. Include the misses. Make it append-only (hash each day's log) so it can't be quietly edited.
- **Methodology page** for the Edge Lab: universe, survivorship handling (include delisted names), borrow costs, look-ahead controls, sample sizes.
- **No touting:** disclose whether the founder trades signaled tickers, and adopt a no-trading window around alerts (see section 4).
- Fintel's reviews show trust dies on **billing and support**. Use self-serve cancellation through the Stripe portal and answer support email.

### 2.3 Onboarding and mobile

- First session: pick 5 tickers or "all under $300M float", choose Discord, email or push, and see a live alert within minutes. Offer a demo replay of yesterday's alerts.
- Mobile: Finviz and DilutionTracker reviewers note no native app (unverified for DilutionTracker). Start with a **PWA plus Web Push**, add Discord (where traders already are), then consider an Expo/React Native shell for iOS push reliability.

---

## 3. Business model and pricing benchmarks

| Tier | Benchmarks |
|---|---|
| Free | Unusual Whales (delayed 15 to 30 min alerts), AskEdgar (20 AI questions), WhaleWisdom, Finviz, OpenInsider, DilutionWatch |
| $20 to $40/mo | Quiver $25, Finviz Elite $39.50 ($24.96 annual), Stocktwits Edge about $30 (secondary), DilutionWatch $19.95 / $39.95 |
| $40 to $80/mo | Unusual Whales $50 / $75, AskEdgar Pro $59, BamSEC $69 (annual), DilutionTracker about $49 to $74 (secondary) |
| $100+/mo | Unusual Whales Max $120, Trade Ideas $127 / $254, Benzinga Essential about $197, AskEdgar $199 |
| Quarterly | WhaleWisdom $90 / $150 per quarter |

**Discord-community model:** Whop trading groups mostly price at $30 to $100/mo (secondary, affiliate guides). Whop takes about 2.7% + $0.30 plus a 3% platform fee on Discord-gated sales (secondary). Selling "callouts" pushes you toward personalized or touting territory. Sell **data-driven bot alerts** into Discord rather than human trade calls.

**Recommendation:**
- **Free:** delayed alerts (15 to 30 min), 3-ticker watchlist, public track record, ticker pages (SEO).
- **Pro, about $29 to $39/mo or about $290/yr:** real-time alerts on all channels, unlimited watchlists, full Edge Lab stats, AI summaries.
- **Later "Desk" tier, about $79/mo:** API/webhooks, backtester, CSV export.
- Use annual discounts of about 20 to 30%, which is standard across Unusual Whales, Finviz and Trade Ideas. Run a 7-day trial (AskEdgar, Quiver) with a card required.
- Also pursue **broker bundling** (CenterPoint-style) as a B2B channel later.

---

## 4. Legal and compliance (US retail research and signals)

*Get a one-hour review from a securities lawyer before charging money. This is a map of the issues, not advice.*

### 4.1 Publisher's exclusion (Lowe v. SEC, 472 U.S. 181 (1985))

- The Advisers Act excludes publishers of "any bona fide newspaper, news magazine or business or financial publication of general and regular circulation."
- Lowe held that impersonal investment newsletters fit the exclusion. The factors were:
  - not personal communications,
  - no false or misleading information,
  - not designed to tout securities the publisher has an interest in.
- **2024 Seeking Alpha decision** (GT Law summary): subscription content plus **customized email alerts** still qualified. Breaking-news updates count as "regular." Subscriber filters on generally available content (watchlist alerts) do not make it personal. This closely matches QuantDesk's watchlist alerts.
- **What breaks it:**
  - personalized communications or authority over funds (*Weiss Research*, 2006),
  - false or misleading content,
  - touting,
  - timing advice to trade your own positions (*SEC v. Park*, 2000).

### 4.2 What not to do

- No personalized advice ("given your account, short XYZ"), no 1:1 chat advice, no portfolio reviews.
- Don't manage money, take discretion, or connect to and **auto-trade users' brokerage accounts**. That is exactly where Weiss lost the exclusion, and it raises broker-dealer and adviser registration issues.
- Don't trade ahead of your own alerts (scalping). Publish a personal-trading policy.
- Keep the AI summaries factual and sourced. An LLM hallucination in a paid alert is "false or misleading information."
- Frame alerts as events and historical statistics ("priced offering; historically median X% over 5d, n=…"), not instructions ("short now").

### 4.3 Hypothetical and backtested performance (Edge Lab, backtester)

- **SEC Marketing Rule (17 CFR 275.206(4)-1)** applies to advisers "registered or required to be registered under section 203". If you stay excluded, it doesn't bind you directly. It still shows what regulators consider fair.
  - Its hypothetical-performance conditions are: policies so it is relevant to the audience, an explanation of criteria and assumptions, and an explanation of risks and limitations.
  - The SEC has said hypothetical performance generally isn't appropriate for mass-audience ads.
  - Enforcement sweeps in 2023 and 2024 hit advisers posting hypothetical performance on websites.
  - Adopt these practices voluntarily.
- **FTC (Section 5, deceptive practices)** applies to everyone. Relevant cases:
  - *Indigo Investment Systems*: hypothetical, hindsight trades shown as real results.
  - *RagingBull* ($2.425M): earnings claims must be typical and substantiated.
  - *Warrior Trading* ($3M): the FTC said disclaimers did not cure misleading earnings claims.
  - *Online Trading Academy*.
  - Takeaway: label simulated results as simulated, show costs and borrow fees, show losers and drawdowns, never use "make $X" claims, and don't rely on fine print.
- **CFTC Rule 4.41** prescribes a hypothetical-performance cautionary statement for commodity advisers. It is not binding for an equities product, but it is a good template for disclaimer wording.

### 4.4 Data licensing

- **SEC/EDGAR:** sec.gov says its information "is considered public information and may be copied or further distributed... without the SEC's permission".
  - Cite the SEC.
  - Don't use the SEC seal.
  - "EDGAR" and the SEC name are registered marks, so don't put them in your product name or domain.
  - Respect 10 req/s and the User-Agent rule.
- **Yahoo / yfinance:** the yfinance README says the Yahoo API "is intended for personal use only," and Yahoo's terms restrict commercial use and automated collection. Fine for your private research. **Not OK as the price source for a paid product.**
- **Licensed price data** (needed for charts and returns shown to users):
  - Massive (ex-Polygon) individual plans are labeled "Individual use only": Starter $29, Developer $79, Advanced $199/mo (real time). Stocks Business is $2,499/mo.
  - Databento US equities: Standard $199/mo with no external distribution listed. Plus $1,750/mo and Unlimited $4,500/mo (annual contracts) include "External distribution". Databento says most datasets can be redistributed after 24 hours.
  - Alpaca: free IEX, Algo Trader Plus $99/mo. Display and redistribution terms were not stated on the data page, so confirm with them.
  - **Cheapest compliant path:** don't display live quotes at first. Compute event-study returns internally from a licensed or delayed source whose terms permit derived statistics, show only aggregates, and link to the user's broker or charting site for prices. Confirm "derived data" rights in writing.
- **News:** show headline, source and link, not full text. Full-text redistribution needs a license (see FEASIBILITY.md).
- **Halts RSS:** Nasdaq's terms bar modifying the content. Display it as is, with attribution.

---

## 5. Distribution: how comparable tools got first users

- **Quiver Quantitative** (launched Feb 2020 by two UW-Madison students):
  - Free dashboards of novel public data (WallStreetBets mentions, congressional trades) came first, with premium following.
  - Reported over 10,000 registered accounts and 200,000 monthly visitors a few months after launch, and 300,000+ registered users later (Benzinga, Wikipedia-style profiles).
  - Lesson: **free, shareable data that people screenshot**.
- **Unusual Whales** (founded June 2020): known for being among the first to catalogue politicians' trades; the founder stays anonymous. No documented growth playbook was found, but the brand is clearly X/FinTwit-native.
- **Stock Analysis** (2019): grew mainly on organic search for individual tickers (third-party traffic estimates vary widely). Lesson: **programmatic ticker pages**.
- **Broker bundling:** DilutionTracker and Benzinga Pro reach traders through CenterPoint's free-tools tiers.
- **Affiliate reviewers** (curvedtrading.com and others) drive "X review" and "X vs Y" search traffic for DilutionTracker.

**Playbook for QuantDesk:**
1. **SEO ticker and event pages:** "/t/XYZ/offerings", "/signals/auditor-changes", each with the public outcome log. Long-tail queries like "XYZ offering" or "XYZ delisting notice" spike exactly when traders care.
2. **X/FinTwit and Stocktwits bot:** auto-post delayed alerts with a chart of historical reaction stats. Delay makes it a teaser, not the product.
3. **Discord:** a free server with delayed alerts and a paid role with real-time alerts, plus a bot other servers can install.
4. **Reddit:** post Edge Lab findings as research (r/Daytrading, r/smallstreetbets, r/algotrading), not ads. Show methodology.
5. **Weekly newsletter:** "Small-cap distress radar". This is also the "regular publication" that supports the publisher's exclusion.
6. Later: affiliate program and broker partnerships.

---

## 6. Technical must-haves for production

| Area | Recommendation |
|---|---|
| **Auth/accounts** | Managed auth (Clerk, Auth.js, Supabase Auth). Email magic link plus Google. Don't roll your own password storage |
| **Payments** | Stripe Checkout, Billing and Customer Portal (self-serve cancel). Costs: 2.9% + 30¢ per US card; Billing 0.7% of volume; Stripe Tax 0.5% per transaction (no-code) where registered |
| **Alert pipeline** | EDGAR poller, then a parser/classifier, then an idempotent signal table (unique on accession number and signal type), then a queue (Postgres LISTEN/NOTIFY or Redis streams), then fan-out workers per channel (Web Push, email via Postmark or SES, Discord webhooks or bot, Expo push later). Record `edgar_accepted_at`, `detected_at` and `sent_at` per alert, and publish p50/p95 latency |
| **Reliability** | Two poller instances with leader election or dedupe; dead-letter queue; retry with backoff; respect SEC limits (one IP flagged = outage) |
| **Monitoring** | Sentry (errors); uptime checks; a "heartbeat" alert if no filing has been ingested in N minutes during market hours; a status page |
| **Data costs** | Start with $0 (EDGAR, FINRA short interest, Nasdaq halts RSS). The first paid upgrade, only once revenue exists and terms allow display: Databento Standard $199/mo, Massive Advanced $199/mo (individual use only, so check commercial terms), or Alpaca $99/mo. External-distribution licenses start around $1,750/mo (Databento Plus) or $2,499/mo (Massive Business) |
| **Mobile push** | Web Push via service worker (PWA) first; Discord as the de facto mobile channel; Expo/FCM/APNs when you ship a native shell |
| **AI summaries** | Cache per accession number; force citations to filing sections; store the prompt version for audit |
| **Legal surface** | Terms of service, disclaimer, privacy policy, personal-trading policy, methodology page |

---

## 7. Prioritized roadmap: MVP to first paying users

1. **Sub-60s EDGAR alert pipeline with measured latency.** Speed is the product's core promise, and every competitor advertises it.
2. **Alert delivery: email, Discord webhook/bot, Web Push.** Traders live in Discord and on phones, and alerts nobody receives are worthless.
3. **Watchlists plus a "universe" filter (float under $300M / $2B).** Personalization through filters keeps you impersonal (Seeking Alpha precedent) and cuts noise.
4. **Ticker page: dilution history, cash runway, public float, FINRA short interest, halts, signal timeline.** This is the "five-second read" users currently get from DilutionTracker, and it also serves as the SEO landing page.
5. **Public, append-only signal track record.** It is the trust moat no competitor has, and it markets itself.
6. **Edge Lab per-signal stats on every alert (n, median move, hit rate, confidence interval).** This is the differentiator versus DilutionTracker: "what usually happens next."
7. **Stripe Checkout, a free tier with delayed alerts, and a Pro tier at about $29 to $39/mo.** Monetize early. The delayed-free model is proven by Unusual Whales.
8. **Legal pack: ToS, disclaimers, hypothetical-performance labeling, personal-trading policy, one-hour lawyer review.** This keeps you inside the publisher's exclusion and FTC norms before you take money.
9. **Distribution engine: delayed-alert X/Discord bot, programmatic SEO pages, weekly newsletter.** These are the cheapest repeatable channels for a solo developer and match how Quiver grew.
10. **Monitoring and ops: heartbeat alerts, Sentry, status page, idempotent fan-out.** A missed or duplicated alert during market hours loses paying users immediately.

*Deliberately later:* the nano-cap short backtester as a paid feature (hypothetical-performance risk; ship it as research with heavy disclosure), a native mobile app, licensed live quotes, an API tier, and broker partnerships.

---

## Sources

**Competitors and pricing**
- AskEdgar pricing: https://askedgar.io/pricing
- AskEdgar on DilutionTracker (competitor-authored): https://www.askedgar.io/blog/9
- DilutionTracker review (affiliate): https://curvedtrading.com/articles/en/reviews/dilutiontracker-review/
- DilutionWatch ranking (self-ranked): https://dilutionwatch.com/articles/best-stock-dilution-trackers.html
- RizeTrade alternatives: https://rizetrade.com/trading-software/dilution-tracker-alternatives
- Dilutracker vs AskEdgar: https://www.dilutracker.com/blog/dilutracker-vs-askedgar
- CenterPoint Edge (free DilutionTracker/Benzinga tiers): https://centerpointsecurities.com/edge/
- BamSEC pricing: https://www.bamsec.com/pricing
- BamSEC/Tegus/AlphaSense: https://sacra.com/research/tegus
- Fintel Trustpilot: https://www.trustpilot.com/review/fintel.io
- Fintel prices (secondary): https://nexusfi.com/d/data-providers/fintel/
- Quiver: https://www.quiverquant.com/pricing/
- Quiver premium vs API: https://www.quiverquant.com/premium-vs-api/
- Unusual Whales pricing: https://unusualwhales.com/pricing
- WhaleWisdom pricing: https://whalewisdom.com/pricing
- TipRanks (secondary): https://www.stockbrokers.com/review/tools/tipranks
- TipRanks (secondary): https://thegodfunded.com/en/tools/tipranks/
- Benzinga Pro (secondary): https://thegodfunded.com/en/tools/benzinga-pro/
- Benzinga Pro (secondary): https://www.creditdonkey.com/benzinga/
- Benzinga Pro Trustpilot: https://pl.trustpilot.com/review/pro.benzinga.com
- Stocktwits Edge (secondary): https://apppricinglab.com/iap/apple/389157776
- Trade Ideas pricing: https://www.trade-ideas.com/pricing/
- Trade Ideas review: https://www.daytrading.com/trade-ideas
- Finviz Elite: https://finviz.com/elite
- Finviz review: https://www.stockbrokers.com/review/tools/finviz
- OpenInsider overview: https://www.tikr.com/blog/5-best-free-tools-to-track-insider-trading-in-stocks
- CapEdge alerts: https://help.capedge.com/edgar-filing-alerts/
- edgar.tools live stream: https://app.edgar.tools/docs/features/live-filings
- PageCrawl: https://pagecrawl.io/blog/sec-filings-monitoring-edgar-alerts
- Whop pricing guide (secondary): https://www.alphaexcapital.com/best-whop-trading-groups/whop-pricing-subscriptions

**Legal**
- Lowe v. SEC: https://law.resource.org/pub/us/case/reporter/US/472/472.US.181.83-1911.html
- Seeking Alpha publisher's exclusion (GT Law): https://www.gtlaw.com/en/insights/2024/8/no-need-for-seeking-alpha-to-seek-registration
- SEC Marketing Rule text: https://www.law.cornell.edu/cfr/text/17/275.206(4)-1
- Marketing Rule hypothetical-performance sweep: https://wilmerhale.com/insights/client-alerts/20231002-ongoing-sec-marketing-rule-enforcement-sweep-results-in-charges-against-investment-advisers
- Marketing Rule practical guide: https://www.troutman.com/insights/the-secs-new-marketing-rule-practically-speaking-hypothetical-performance/
- FTC Online Trading Academy: https://www.ftc.gov/news-events/news/press-releases/2020/09/ftc-settlement-requires-online-trading-academy-forgive-consumer-debt-principals-turn-over-millions
- FTC Warrior Trading: https://advertisinglaw.fkks.com/post/102hn6f/ftc-gets-3m-settlement-over-false-money-making-claims
- FTC earnings claims: https://www.olshanlaw.com/Advertising-Law-Blog/ftc-once-again-focuses-on-earnings-claims
- CFTC 4.41 amendment: https://www.govinfo.gov/content/pkg/FR-2007-02-23/pdf/E7-3122.pdf

**Data**
- SEC site dissemination policy: https://www.sec.gov/privacy
- Accessing EDGAR data (rate limit): https://www.sec.gov/os/accessing-edgar-data
- SEC developer resources: https://www.sec.gov/developer
- SEC RSS feeds: https://www.sec.gov/structureddata/rss-feeds
- yfinance disclaimer: https://github.com/ranaroussi/yfinance
- Yahoo ToS: https://legal.yahoo.com/us/en/frontier/terms/otos/index.html
- Massive pricing: https://massive.com/pricing
- Massive business pricing: https://massive.com/business
- Polygon to Massive rebrand: https://fisd.net/polygon-io-is-now-massive
- Databento pricing: https://databento.com/pricing
- Alpaca data: https://alpaca.markets/data
- FINRA short interest: https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data
- Nasdaq halt RSS terms: https://m.nasdaqtrader.com/content/administrationsupport/agreementstrading/THRSSFeedTermsCond.pdf

**Distribution and technical**
- Quiver origin (Benzinga): https://benzinga.com/fintech/20/07/16490696/quiver-quant-and-its-young-founders-are-changing-accessibility-to-alternative-data
- Quiver (Cap Times): https://captimes.com/news/business/madisons-quiver-quantitative-wants-to-shake-up-stock-trading/article_49d12cdc-67e1-5585-8387-f60325f5e222.html
- Unusual Whales (Benzinga): https://www.benzinga.com/news/22/01/25015596/exclusive-unusual-whales-creates-nancy-pelosi-etf-so-you-can-track-her-trades
- Stock Analysis about page: https://stockanalysis.com/about/
- Stripe pricing: https://stripe.com/pricing
