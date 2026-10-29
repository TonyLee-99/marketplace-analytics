# Marketplace: state of the business and three decisions

**To:** VP Marketplace · **Data:** Olist, Jan-2017 to Aug-2018 (real orders) · **Read time:** 5 min

## State of the business
- **Growth is all acquisition.** GMV Jan–Aug 2018 was R$7.34M, **+138% YoY**. Breaking it into customers × frequency × AOV: customers grew +139%, orders per customer −0.6%, AOV +0.4%. The growth was broad-based: no category added more than 12% of it. [1]
- **Customers almost never come back.** Only **3.0%** of buyers ever order twice; just 1.9% come back on a later day within 180 days. Repeat orders are 2.9% of GMV. Lifetime value ≈ the first order, so CAC has to pay back on that first order. [2]
- **Delivery is fast but over-promised, and it broke in Feb–Mar 2018.** On-time is 93.2% overall but fell to **81.0% for March-2018 orders**. The root-cause engine finds the Feb drop happened inside every segment (network-wide), not through a change in mix: rate effect −8.5 pp, mix effect +0.05 pp. The median parcel arrives **12 days before its promise**. [3]
- **Late hurts reviews, not repurchase.** For the same seller in the same month, a late order scores **−1.89 stars**. With actual delivery time held fixed, simply breaking the promise costs −1.26. The effect on 180-day repurchase is −0.29 pp (95% CI −0.75 to +0.17, not significant). Repurchase is too rare for lateness to cost much GMV: about R$2k/yr. [4]

## Recommendations (in priority order)
| # | Decision | Sized impact (12 months) | Confidence |
|---|---|---|---|
| 1 | **A/B test a calibrated delivery promise.** Show the lane-level P80 of recent delivery times, retrained monthly, instead of today's padded estimate. | Promise **4.2 days shorter** on average. Simulated late rate 4.4% → 7.0% (exactly at the 93% on-time target). Review −0.03 stars; repurchase GMV at risk R$0.8k. Upside **R$114k–458k** if each promise-day saved lifts conversion 0.25–1.0% (published range; not measurable here). | Cost: **high** (measured on held-out months). Upside: **low** until the A/B test reads out. The test is cheap and reversible. |
| 2 | **Fix the 10 worst lanes, starting with SP→RJ** (6,175 orders, 17.6% late vs 7.8% network). Carriers cause 80% of the misses, so renegotiate the carrier SLA or switch carrier on these lanes. | **1,143 fewer late orders** and about **586 fewer 1–2★ reviews**; R$153k of GMV no longer arriving late. | **High** on size (the review effect holds within seller-month). Medium on how much is fixable. |
| 3 | **Stop shipping partial orders as "delivered".** Hold the delivered status until every item has arrived, tell customers about split shipments, and put the 82 "fix-first" sellers (22% of GMV, 87% on-time) on a 60-day quality plan. | "Incomplete order" is **15% of all 1–2★ texts** and the **#1 complaint on orders delivered on time (22%)**: 1,622 reviews on R$367k of orders over 20 months, about 970 reviews/yr. 65% are multi-item orders, which are only 12% of reviews with text. | Medium: the text classifier is 71% accurate on hand-labelled reviews. |

**What not to do:** don't fund a retention program on the expectation that faster delivery will bring buyers back. Fixing every late delivery would recover roughly R$2k/yr of repeat GMV. Growth comes from acquisition and assortment.

---
### Appendix: methodology and caveats
- **Sources** (all reproducible with `make all`, values listed in docs/RESULTS.md): [1] reports/growth.json (exact log/LMDI decomposition, residual 1e-16) · [2] reports/cohorts.json (Kaplan–Meier, same-day split baskets excluded) · [3] reports/root_cause.json, reports/promise_policy.json · [4] reports/delivery_impact.json · lanes/sellers: reports/lanes.json, reports/sellers.json · text: reports/voc.json.
- **Metrics** come from the governed layer (metrics/metrics.yml). GMV is item price on non-canceled orders, by purchase date. On-time compares the delivered DATE with the promised date, by purchase month. A timestamp comparison would read 1.3 pp lower, and delivery-month cohorting would show April 2018 at 82.9% instead of 95.5%.
- **Causality.** Review effects use OLS with seller, category, state and month fixed effects (SEs clustered by seller), a within-seller-month design, and a same-delivery-time design. A regression-discontinuity check at the promise date gives −0.24 stars (±5 days), but the bunching test fails (orders bunch just before the promise), so it is supporting evidence only.
- **Promise simulation.** The model was tested out-of-time on Apr–Aug 2018 purchases; each month was predicted with data available before it. P80/P90 coverage came out at 91% / 95%, above nominal because the network kept getting faster, so the promises lean safe. Review impact uses the same-delivery-time dose-response. The conversion benefit is an **assumption** (Fisher, Gallino & Xu 2019, J. Marketing Research: +1.45% sales per business day faster delivery).
- **Text.** Keyword rules were run on all 40,514 reviews with text. They were checked against 400 hand-labelled reviews (70.6% accuracy on the fresh holdout, macro-F1 0.61); local qwen2.5:7b scored 77% on the 31 gold reviews it reached before the shared laptop ran out of memory. The gold labels were made by the analyst (not a native speaker) and need a spot-check.
- **Not in the data:** costs, margins, refunds, sessions/conversion and Olist's real targets. Targets on the dashboard are illustrative.
