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

## Results
(filled in at the end of the build)
