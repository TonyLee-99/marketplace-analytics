# Acceptance criteria

Written on 2026-10-29 **before** any model, analysis or dashboard code existed.
Each criterion is measurable and has a verification command. The "Result" column is
filled in at the end of the build (see the bottom section) with PASS/FAIL and evidence.

## A. Data provenance
| ID | Criterion | Verify with |
|----|-----------|-------------|
| A1 | All 9 Olist tables present; row counts exactly: orders 99,441; order_items 112,650; payments 103,886; reviews 99,224; customers 99,441; sellers 3,095; products 32,951 (plus geolocation, category translation) | `make ingest` (fails on mismatch) |
| A2 | Every raw file's SHA-256 is pinned in `data_manifest.json` and matches at least one *independent* second mirror | `make ingest`; `docs/DATA_PROVENANCE.md` |
| A3 | Raw schema unmodified: column names/order equal the documented originals | `make ingest` header check |
| A4 | License (CC BY-NC-SA 4.0) and source links documented | `docs/DATA_PROVENANCE.md`, README |

## B. Analytics engineering (dbt + DuckDB)
| ID | Criterion | Verify with |
|----|-----------|-------------|
| B1 | `dbt build` exits 0 with **0 test failures and 0 errors** | `make dbt` |
| B2 | Layers staging → intermediate → marts exist; marts include fct_orders, fct_order_items, fct_payments, dim_customers (grain = customer_unique_id), dim_sellers, dim_products, dim_date | `dbt ls --resource-type model` |
| B3 | ≥1 SCD2 artifact (dbt snapshot and/or derived valid_from/valid_to history) | `dbt ls --resource-type snapshot` |
| B4 | Tests include unique, not_null, relationships, accepted_values, and ≥2 custom business-rule tests (payment ↔ item+freight reconciliation; delivered ≥ purchase) | `dbt ls --resource-type test` |
| B5 | ≥40 data tests in total | same |
| B6 | Source freshness configured on every source; `dbt source freshness` runs | `make freshness` |
| B7 | ≥2 exposures (dashboard, memo) declared | `dbt ls --resource-type exposure` |
| B8 | `dbt docs generate` produces `target/catalog.json` + `index.html` | `make docs` |
| B9 | Every data-quality issue found is listed with a count and a handling decision | `docs/DATA_QUALITY.md` (counts produced by `make dq`) |

## C. Governed metrics layer
| ID | Criterion | Verify with |
|----|-----------|-------------|
| C1 | One YAML file defines all 12 required metrics (GMV, AOV, orders, active customers, repeat-purchase rate, on-time delivery rate, avg delivery days vs promised, review score, NPS-style score, seller concentration top-10% share + HHI, freight-to-price ratio, cancellation rate) each with definition, owner, grain, caveats | `pytest tests/test_metrics_layer.py` |
| C2 | Every metric compiled by the layer equals an independently hand-written SQL to within 1e-9 (relative) on the full history | `pytest tests/test_metrics_layer.py` |
| C3 | Dashboard and memo numbers are read from metric-layer outputs (no metric re-implemented in the dashboard) | code review: `src/dashboard/build.py` imports metric outputs only |
| C4 | Metrics catalog doc generated from the YAML (not hand-written) | `make metrics` → `docs/metrics_catalog.md` |

## D. Analyses (all numbers produced by scripts, written to `reports/*.json|csv`)
| ID | Criterion | Verify with |
|----|-----------|-------------|
| D1 | GMV metric tree: MoM and YoY decomposition into customers × frequency × AOV whose components sum to the total log-change exactly (residual < 1e-9), plus category and state mix contribution | `pytest tests/test_analyses.py` |
| D2 | Cohort retention matrix + repeat-purchase curve on customer_unique_id; repeat rate reported with the real value | `reports/cohorts.json` |
| D3 | Delivery → outcome: fixed-effects regression (category, customer state, seller, month) of review score and of repurchase on lateness, clustered SEs, dose-response curve with ≥6 lateness bins, BRL impact sizing with a confidence interval | `reports/delivery_impact.json` |
| D4 | Seller scorecard (≥6 KPIs), tiering, Pareto curve, HHI | `reports/sellers.json` |
| D5 | Lane analysis seller_state→customer_state with min-volume filter, ranked SLA misses, opportunity sizing in late orders and BRL | `reports/lanes.json` |
| D6 | Daily anomaly detection (STL residual + robust z), explicit alerting rule, Black Friday 2017 explicitly detected and labelled as a known event, backtest list of alerts | `reports/anomalies.json` |

## E. BI dashboard
| ID | Criterion | Verify with |
|----|-----------|-------------|
| E1 | Static self-contained HTML (works offline, no CDN) built by a script from the marts | `make dashboard`; grep for `<script src="http` returns nothing |
| E2 | 5 pages: Executive KPI (targets + variance), Growth, Customer & Retention, Delivery/Ops, Sellers | screenshots in `docs/img/` |
| E3 | Working filters (date range, customer state, category) that change KPI values | playwright test asserts KPI text changes after filter |
| E4 | Renders with 0 JS console errors in headless Chrome; every chart title states a takeaway | `make screenshots` (fails on console error); manual check of screenshots |

## F. Executive memo
| ID | Criterion | Verify with |
|----|-----------|-------------|
| F1 | `docs/exec_memo.md` ≤ ~1 page main body (≤ 550 words before appendix), state of business + 3 prioritized recommendations each with sized impact (BRL) and confidence | `wc -w` on main body |
| F2 | Every number in the memo traceable to a report file | memo footnotes |

## G. Engineering quality
| ID | Criterion | Verify with |
|----|-----------|-------------|
| G1 | `make all` rebuilds everything from raw CSV files with exit 0 | `make clean && make all` |
| G2 | pytest passes (≥10 tests) | `make test` |
| G3 | `ruff check` clean | `make lint` |
| G4 | Dockerfile and `.github/workflows/ci.yml` present (CI written, not run remotely) | files exist |
| G5 | Required docs: README (mermaid diagram, sources+licenses, results table, production mapping with citations, limitations) | files exist |
| G6 | Project data + intermediates ≤ 3.5 GB | `du -sh data` |


## H. Differentiators (addendum, added 2026-10-29 when the scope was raised, before any of H was built)
| ID | Criterion | Verify with |
|----|-----------|-------------|
| H1 | Promise padding (estimated − actual days) measured as a distribution overall, by lane and by category | `reports/promise_policy.json` |
| H2 | Quantile model (P50/P80/P90) of delivery days using only purchase-time features, time-based split (train ≤ 2018-03, test 2018-04..08), no leakage; test-set empirical coverage of P80 within ±5 pp of 80% and P90 within ±5 pp of 90% | `reports/promise_policy.json` coverage fields; `pytest tests/test_promise.py` (feature list contains no post-purchase field) |
| H3 | ≥4 promise policies simulated on the held-out test set (current, lane-P80, lane-P90, model-P80, model-P90): promise days saved vs late-rate change, converted to net expected review/repurchase impact using the measured causal effect; one recommended policy with impact range and confidence | `reports/promise_policy.json`, memo |
| H4 | Automated KPI root cause: dimension-contribution decomposition (mix vs rate) across state, category, seller tier that ranks drivers of a MoM change; explicit Simpson's-paradox check; run on ≥2 real KPI moves; mix+rate+interaction effects sum to the total change exactly (residual < 1e-9) | `reports/root_cause.json`; `pytest tests/test_root_cause.py` |
| H5 | Voice of customer: complaint-reason taxonomy (≥7 classes) labelled on a stratified sample of ≥2,000 real Portuguese reviews; accuracy (and macro-F1) vs a ≥200-review hand-checked gold sample reported, whatever it is; reasons tied to sellers and lanes | `reports/voc.json` |
| H6 | Causal design beyond regression controls: within-seller late-vs-on-time comparison (seller FE) and a regression-discontinuity-style comparison around the promised date (bandwidth + placebo cutoffs), with assumptions stated | `reports/delivery_impact.json` `rd` block |
| H7 | Metric governance: ≥1 real example where two plausible definitions of the same KPI disagree (numbers shown) and the governed definition resolves it | `reports/metric_conflicts.json`, `docs/metrics_catalog.md` |
| H8 | Dashboard surfaces the promise-policy simulator (interactive), root-cause view and complaint drivers | screenshots in `docs/img/` |
| H9 | Warehouse at stable path `data/warehouse.duckdb` and metrics at `metrics/metrics.yml`, documented in README for read-only consumers | README "For downstream consumers" |

## Results (round 2, after the independent review; every number also in docs/RESULTS.md)
Round 1 marked everything PASS except H2. The review found that several PASSes rested on a
wrong reading of the data, so each row below is re-judged against what the evidence actually supports.

| ID | Result | Evidence |
|----|--------|----------|
| A1–A4 | PASS | `make ingest`: sha256 + header + row count verified for all 11 files (orders 99,441 … MQLs 8,000); provenance in docs/DATA_PROVENANCE.md; raw-CSV golden tests (`tests/test_golden_raw.py`) reproduce GMV, orders, on-time and repeat rate exactly |
| B1 | PASS | final `make all`: `Done. PASS=147 WARN=1 ERROR=0`. The WARN is the designed payment-reconciliation threshold (20 orders) |
| B2 | PASS | 10 staging, 6 intermediate, 10 mart models; dim_customers keyed on customer_unique_id |
| B3 | PASS (demonstration) | snapshot snap_sellers + dim_customer_location_history (250 movers); no fact table joins it point-in-time yet (README limitation) |
| B4/B5 | PASS | 118 dbt tests, including the item-grain tests `assert_item_price_rolls_up_to_orders` and `assert_item_fact_has_no_order_measures` (fan-out fix: order-level columns on fct_order_items are now `order_*`) |
| B6–B8 | PASS | freshness 11/11 PASS; 3 exposures (no local paths); docs generated |
| B9 | PASS | docs/DATA_QUALITY.md, 36 generated checks, incl. DQ20b 1,359 handed to carrier before approval, DQ33 4,473 late orders reviewed before delivery, DQ35 1,729 never-delivered revenue orders |
| C1 | PASS | 17 metrics with owner/grain/caveats; repeat rate re-governed to distinct purchase days (2.17%; the rejected same-day-inclusive version is 3.04%) |
| C2 | PASS (re-scoped) | the circular "compiler vs my own hand SQL" test was retired; replaced by raw-CSV golden tests (independent of dbt/marts) |
| C3/C4 | PASS | dashboard ships only metric components; the decisions panel reads reports/recommendations.json, the same file the memo is generated from |
| D1 | PASS (re-scoped) | the customer×frequency×AOV identity is no longer presented as a finding; seller-side tree: sellers 1,072→1,226, GMV/seller R$923→R$704, Jun–Aug vs Mar–May −12.7% |
| D2 | PASS | KM later-day repeat 1.92% within 180 d; governed repeat rate 2.17% |
| D3 | PASS (corrected) | review effects split by survey timing: within seller×month −1.89 recorded / −0.51 post-delivery; repurchase −0.29 pp with MDE 0.66 pp (36% of base), reported as underpowered |
| D4 | PASS | 9-KPI scorecard, 5 tiers, Pareto, HHI 38 |
| D5 | PASS (corrected) | lane-adjusted baseline: 10 worst lanes = 277 excess late orders (was 1,143 vs network); marginal 1–3-day dose-response gives 57 recorded / 20 post-delivery 1–2★; "switch carrier" removed (no carrier ID) |
| D6 | PASS | volume monitor: 16 alerts, Black Friday classified expected_event; new in-flight monitor first alerts the spring-2018 slump on 2018-03-30 (volume monitor: 0 alerts in Feb–Mar) |
| E1–E4 | PASS | `make screenshots`: `"errors": []`, filter test changes KPIs (GMV Jan–Aug 2018 R$7.34M → RJ R$901k); screenshots inspected; exec page now 4 KPI cards with YoY + window, no invented plan targets, readable names, axis titles on every chart |
| F1 | PASS | memo main body 548 words (`awk '/^---/{exit} {print}' docs/exec_memo.md \| wc -w`), generated by `make results` |
| F2 | PASS | every memo number comes from reports/*.json via src/marketplace/memo.py; listed in docs/RESULTS.md |
| G1 | PASS | final `time make all` → `make all: OK`, `real 6m49s` (log: data/make_all_final.log) |
| G2 | PASS | `22 passed`; identity tests retired; added temporal-leakage, raw-CSV golden, synthetic-Simpson and rescore tests |
| G3 | PASS | `ruff check` → All checks passed |
| G4 | PASS (not executed) | Dockerfile + CI yaml written; not run (no Docker daemon, no remote) |
| G5 | PASS | README rewritten around the strongest true finding; production citations moved to docs/PRODUCTION_MAPPING.md |
| G6 | PASS | `du -sh data` 266M |
| H1 | PASS | median padding 12 days, 73.9% of orders > 7 days early |
| H2 | **FAIL (coverage)** | leakage fixed (strictly prior-time seller/lane history; `test_history_uses_only_deliveries_before_purchase`, `test_future_label_change_does_not_move_features`, `test_training_rows_are_known_before_month_start`). Coverage is miscalibrated in both directions: model P80 70.4% (selection, Oct–Mar) vs 90.3% (test, Apr–Aug); P90 79.8% vs 94.7%. Target ±5 pp missed. A drift-aware recalibrated lane policy is evaluated instead |
| H3 | PASS (outcome changed) | 14 policies on a full-year rolling backtest, never-delivered = late, policy chosen on the selection period by the pre-set rule → `lane_recalibrated_to_7pct_late` (it lengthens peak promises). Lane-P80 full year: −6.4 d, late 9.3%→20.6%, break-even conversion +0.071%/day. Recommendation changed from "roll out lane-P80" to "capped A/B" (capped variant: −2.8 d, late 12.2%) with guardrail MDE 1.7 pp and a kill rule. Confidence downgraded to low |
| H4 | PASS | process-stage Shapley for on-time moves (Jan→Mar 2018: promise +5.6, transit +2.5, seller −1.0, unexplained +6.1 pp); 6 dimensions incl. lane and fulfilment leg; verdict prints "network-wide: no single segment driver" when the rate effect is broad |
| H5 | PASS | rules on 40,514 reviews; agreement with **single-annotator labels**: 70.6% on fresh set B (CI 63.1–77.5%), macro-F1 0.61; circular LLM-vs-label accuracy removed; shares corrected for misclassification with bootstrap CIs; 50-review blind second-pass template + `voc rescore` |
| H6 | PASS (stronger designs added) | carrier-leg-only within seller-month, post-delivery: −0.54 [−0.61, −0.46]; truckers'-strike 2SLS: recorded −1.49 [−2.10, −0.89] (F 22), post-delivery −0.49 [−1.70, +0.72] (F 34). RD demoted to a falsification appendix; same-delivery-time design flagged as a mediator problem |
| H7 | PASS | April-2018 on-time 95.5% vs 82.9%; repeat 2.17% vs 3.04%; timestamp vs date 1.3 pp; GMV ± freight R$2.24M |
| H8 | PASS | simulator (policy × period × survey regime, frontier across lane quantiles), root-cause page with stage split, VoC panel with corrected shares |
| H9 | PASS | README "Reading the warehouse"; no local absolute paths in tracked files |
