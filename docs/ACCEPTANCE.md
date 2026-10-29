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

## Results
Filled in 2026-10-29 at the end of the build. Evidence = command + output excerpt (numbers also in docs/RESULTS.md).

| ID | Result | Evidence |
|----|--------|----------|
| A1 | PASS | `make ingest` → `raw.orders 99,441 … raw.products 32,951 rows (sha256 + header + count verified)`; also geolocation 1,000,163, translation 71, closed deals 842, MQLs 8,000 |
| A2 | PASS | data_manifest.json pins sha256. LFS sha256 of 4 files equals HF API oids of bulutttt/olist-raw-data and MafiaAzulBr/olistcsv; git blob ids of the 5 small files match; funnel sha256 identical across 2 GitHub mirrors (docs/DATA_PROVENANCE.md) |
| A3 | PASS | ingest compares headers with the manifest (fails otherwise); the original misspellings (`lenght`) and BOM are preserved |
| A4 | PASS | docs/DATA_PROVENANCE.md, README "Data sources and license" |
| B1 | PASS | `dbt build` → `Done. PASS=144 WARN=1 ERROR=0 SKIP=0`. The WARN is the designed threshold test (20 unexplained payment mismatches, errors only above 493) |
| B2 | PASS | `dbt ls --resource-type model`: 10 staging, 6 intermediate, 10 marts incl. fct_orders, fct_order_items, fct_payments, dim_customers (PK customer_unique_id, 96,096 rows), dim_sellers, dim_products, dim_date |
| B3 | PASS | snapshot `snap_sellers` (check strategy) + `dim_customer_location_history` (valid_from/valid_to/is_current; 250 people with >1 address); `assert_scd2_no_overlap` passes |
| B4 | PASS | 115 tests: unique, not_null, 16 relationships, 6 accepted_values, 4 within_range, value_at_least_column, plus singular `assert_payments_reconcile_to_items`, `assert_delivered_not_before_purchase`, `assert_gmv_conserved_staging_to_marts`, `assert_scd2_no_overlap`, `assert_one_customer_per_person_in_dim` |
| B5 | PASS | `dbt ls --resource-type test | wc -l` → 115 (≥40) |
| B6 | PASS | `dbt source freshness` → 11 of 11 sources PASS (warn 24 h / error 72 h on `_loaded_at`) |
| B7 | PASS | 3 exposures: executive_dashboard, executive_memo, analytics_agent_readonly |
| B8 | PASS | `dbt docs generate` → `Catalog written to …/target/catalog.json`; target/index.html exists |
| B9 | PASS | docs/DATA_QUALITY.md: 32 generated checks with counts and handling (e.g. DQ01 3,345 order-scoped customer ids; DQ09 280,009 duplicate geolocation rows; DQ24 20 unexplained payment mismatches) |
| C1 | PASS | `pytest tests/test_metrics_layer.py::test_catalog_complete` passes; metrics.yml defines 17 metrics, each with definition/owner/grain/caveats |
| C2 | PASS | `test_metric_equals_hand_sql` passes for 14 metrics, rel_tol 1e-9 (GMV, orders, AOV, active customers, repeat rate, on-time, delivery days, days vs promise, review, NPS-style, freight ratio, cancellation, HHI, top-10% share) |
| C3 | PASS | src/marketplace/dashboard/build.py only ships MetricsLayer.components()/compute() outputs; app.js sums num/den and evaluates `formula` strings from metrics.yml |
| C4 | PASS | `make metrics` writes docs/metrics_catalog.md (header: "Generated from metrics/metrics.yml … Do not edit by hand") |
| D1 | PASS | `test_growth_report_residuals` passes (all MoM/YoY/YTD log residuals < 1e-9; YTD 1.1e-16). Category and state contributions are in growth.json |
| D2 | PASS | cohorts.json: 20 cohort retention rows, KM curves, lifetime repeat rate 3.04% stated plainly |
| D3 | PASS | delivery_impact.json: FE models clustered by seller; 8-bin dose-response; impact block with 95% CI (lost repeat GMV R$2.2k, CI −R$1.3k…R$5.8k) |
| D4 | PASS | sellers.json + reports/seller_scorecard.csv: 9 KPIs per seller, 5 tiers, Pareto curve, HHI 38 |
| D5 | PASS | lanes.json: 61 lanes ≥100 orders, ranked by excess late orders, sized in orders, 1–2★ reviews and BRL GMV (top 10: R$152.6k on excess-late orders) |
| D6 | PASS | anomalies.json: rule stated; online STL backtest gives 16 alerts. Black Friday 2017 `flagged_online: true, classification: expected_event` (z 12.8) |
| E1 | PASS | `make dashboard` → dashboard/index.html (6.3 MB, plotly inlined); `test_dashboard_self_contained_with_all_pages` asserts no external `<script src=http…>` |
| E2 | PASS | docs/img/dashboard_{exec,growth,customers,delivery,sellers,rca}.png. 6 pages: the 5 required plus "Why did it move?" |
| E3 | PASS | reports/dashboard_check.json: `kpis_changed_with_state_filter: true`, `kpis_changed_with_category_and_date_filter: true` (GMV card R$13.45M → R$1.80M for RJ) |
| E4 | PASS | `make screenshots` → `"errors": []`, 0 empty charts. Screenshots inspected by eye; two layout bugs found that way were fixed (padding histogram mis-serialised; overlapping frontier labels). All chart titles state a takeaway |
| F1 | PASS | main body of docs/exec_memo.md = 543 words (`awk '/^---/{exit} {print}' docs/exec_memo.md \| wc -w`); 3 prioritized recommendations with BRL/size and confidence |
| F2 | PASS | memo footnotes [1]–[4] plus the appendix map every number to reports/*.json; docs/RESULTS.md is generated from those files |
| G1 | PASS | Fresh `git clone` of commit HEAD into a scratch dir with only data/raw copied in, then `time make all` → `Done. PASS=144 WARN=1 ERROR=0` … `32 passed` … `All checks passed!` … `make all: OK`, `real 24m39s`. Its docs/RESULTS.md matches this repo on every row except the multithreaded-GBM promise model (P80 coverage 91.4% vs 91.0%, P90 95.4% vs 95.3%, pinball 1.38 vs 1.37) |
| G2 | PASS | `make test` → `32 passed` |
| G3 | PASS | `ruff check src tests` → `All checks passed!` (E501 handled by `ruff format`) |
| G4 | PASS | Dockerfile, .dockerignore, .github/workflows/ci.yml present. Not executed: Docker daemon not running locally, CI not pushed |
| G5 | PASS | README.md (mermaid, sources+licenses, results table, production mapping with citations, limitations, downstream-consumer section) |
| G6 | PASS | `du -sh data` → 266M (≤3.5 GB) |
| H1 | PASS | promise_policy.json padding: median 12 days, 74% > 7 days early; most/least padded lanes (≥200 orders, 48 lanes) and categories |
| H2 | **FAIL (partial)** | Leakage-free and time-based: PASS (`test_no_post_purchase_features`; rolling retrain on months M-w-1..M-2 with labels known before M; window chosen on the 2017-10..2018-03 backtest). Coverage target: **FAIL**. Test P80 coverage 91.0–91.4% across runs (target 80 ±5) and P90 95.3–95.4% (target 90 ±5, misses by 0.3–0.4 pp). Cause: delivery kept speeding up in 2018 (median 13 → 7 days). The model still beats the lane-quantile baseline and Olist's estimate on pinball loss (P90 1.38 vs 1.57 vs 1.61). The static split plus conformal calibration over-covered even more (P80 94.4%, P90 97.2%). Multithreaded HGB gives run-to-run differences of about 0.1 pp |
| H3 | PASS | 7 policies simulated; recommendation rule fixed before results; recommended lane_p80: −4.2 days, late 4.4% → 7.0%, review −0.033, repurchase GMV at risk R$771/yr (CI −R$454…R$2.0k), conversion upside R$114k–458k/yr (assumed elasticity). Confidence stated in the memo |
| H4 | PASS | root_cause.json: 6 auto-detected moves × 3 dimensions; `test_root_cause_effects_add_up` (full-precision residual < 1e-9); Simpson scan of 114 cases (7 reversals, 0 material) |
| H5 | PASS (with deviation) | 10-class taxonomy. Primary labeller is keyword rules on all 40,514 reviews with text (≥2,000). Accuracy on the fresh blind holdout B (n=160) is 70.6% (95% CI 63.1–77.5%), macro-F1 0.61, vs a 27.5% majority baseline; gold A (n=240) 71.7%. Tied to sellers and lanes. Deviation: the Ollama qwen2.5:7b run stopped at 400 of the 3,000-review sample because the shared laptop ran out of memory (75–120 s per request). On the 31 gold items it reached it scored 77.4%; rule/LLM agreement is 64.8% on 400 |
| H6 | PASS | within-seller-month −1.89 [−1.95, −1.84]; same delivery time −1.26; RD at 4 bandwidths, 3 placebo cutoffs and a density check, with assumptions stated. The density check fails (ratio 0.64 vs 0.88) and one placebo is significant (p = 0.04), so the RD is reported as supporting evidence only |
| H7 | PASS | metric_conflicts.json: repeat rate 3.04% vs 0%; April 2018 on-time 95.5% vs 82.9%; timestamp vs date 1.3 pp; GMV ±freight R$2.24M. Each is resolved in metrics.yml `rejected_alternatives` |
| H8 | PASS | Delivery page has an interactive promise simulator (policy + elasticity selectors, frontier chart); "Why did it move?" page has the root cause; Sellers & VoC page has complaint drivers (screenshots) |
| H9 | PASS | README "For downstream consumers": data/warehouse.duckdb (read-only), metrics/metrics.yml, schemas listed |
