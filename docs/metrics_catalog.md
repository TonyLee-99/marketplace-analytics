# Metrics catalog

_Generated from `metrics/metrics.yml` by `python -m marketplace.metrics`. Do not edit by hand._

| Metric | Definition | Owner | Grain | Target |
|---|---|---|---|---|
| **GMV (BRL)** (`gmv`) | Sum of item prices (excluding freight) on revenue orders, i.e. orders whose status is not canceled/unavailable and that have at least one item, dated by purchase. | Marketplace Finance | order; bucketed by purchase_date | trailing 3-month average x 1.03 (momentum plan) |
| **Orders** (`orders`) | Count of revenue orders (same filter as GMV). | Marketplace Finance | order; bucketed by purchase_date | trailing 3-month average x 1.03 |
| **Average order value (BRL)** (`aov`) | GMV divided by revenue orders (item price only, excl. freight). | Marketplace Finance | order; bucketed by purchase_date | - |
| **Active customers** (`active_customers`) | Distinct people (customer_unique_id) with >=1 revenue order in the period. | Growth | person (customer_unique_id); bucketed by purchase_date | - |
| **Returning-customer share** (`repeat_purchase_rate`) | Share of the period's active customers who bought on a later calendar DAY than their first purchase (customer_purchase_day_number >= 2, computed on customer_unique_id). Same-day split baskets are not repeat purchases. | Growth | person; bucketed by purchase_date | illustrative: 5% returning share |
| **On-time delivery rate** (`on_time_delivery_rate`) | Delivered orders whose delivery DATE is on or before the promised (estimated) date, over all delivered orders, attributed to the month the order was placed. | Logistics Ops | delivered order; bucketed by PURCHASE date (promise cohort) | illustrative: 93% |
| **Avg delivery days (purchase -> customer)** (`avg_delivery_days`) | Mean fractional days from purchase timestamp to delivery timestamp. | Logistics Ops | delivered order; bucketed by purchase date | - |
| **Avg promised days** (`avg_promised_days`) | Mean whole days from purchase date to the estimated delivery date shown to the customer. | Logistics Ops | delivered order; bucketed by purchase date | - |
| **Avg delivery vs promise (days, + = late)** (`avg_days_vs_promise`) | Mean of (delivered date - promised date). Negative = arrived early (padding). | Logistics Ops | delivered order; bucketed by purchase date | - |
| **Avg review score (1-5)** (`avg_review_score`) | Mean review score of revenue orders, using the latest review when an order has several. | Customer Experience | reviewed order (latest review per order); bucketed by purchase date | illustrative: 4.2 |
| **Share of 5-star reviews** (`pct_5_star`) | Share of reviewed revenue orders scoring 5. | Customer Experience | reviewed order | - |
| **Share of 1-2 star reviews** (`pct_1_2_star`) | Share of reviewed revenue orders scoring 1 or 2. | Customer Experience | reviewed order | - |
| **NPS-style score** (`nps_style_score`) | Percent 5-star minus percent 1-2-star, x100 (range -100..100). A proxy only: real NPS asks a 0-10 likelihood-to-recommend question, which Olist does not collect. | Customer Experience | reviewed order | illustrative: 45 |
| **Freight / item price** (`freight_to_price_ratio`) | Total freight charged divided by total item price on revenue orders (value-weighted). | Logistics Ops | order | - |
| **Cancellation rate** (`cancellation_rate`) | Orders ending canceled or unavailable over all orders placed. | Marketplace Ops | order (all statuses) | illustrative: <= 1.0% |
| **Top-10% sellers' share of GMV** (`seller_top10pct_gmv_share`) | Rank the period's active sellers by GMV; share of GMV earned by the top 10% of them (ceil(0.1 x active sellers)). | Marketplace Strategy | seller within period | - |
| **Seller HHI (0-10,000)** (`seller_hhi`) | Herfindahl-Hirschman index of seller GMV shares (sum of squared % shares). | Marketplace Strategy | seller within period | - |

## Caveats per metric

### GMV (BRL) (`gmv`)
- Type: `simple`; unit: BRL
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, sum(items_price_brl) filter (where is_revenue_order) as value from marts.fct_orders where true group by 1
  ```
- Excludes freight (pass-through to carriers). GMV incl. freight is ~16% higher.
- Orders still in shipped/invoiced/processing status count (not yet delivered).
- Not net of returns; Olist does not publish refunds.
- Rejected alternative `gmv_incl_freight`: Freight is passed through to carriers; including it inflates GMV and mixes logistics cost changes into growth.
- Rejected alternative `gmv_incl_canceled`: Canceled/unavailable orders never became revenue.
- Rejected alternative `gmv_payment_based`: Payments include instalment interest and voucher top-ups; finance's ledger basis, not merchandise value.

### Orders (`orders`)
- Type: `simple`; unit: count
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, count(*) filter (where is_revenue_order) as value from marts.fct_orders where true group by 1
  ```
- 775 orders have no items in the source (mostly unavailable/canceled) and are excluded.

### Average order value (BRL) (`aov`)
- Type: `derived`; unit: BRL
- Formula: `gmv / orders`
- Mean is skewed by a long right tail (max single order > 13,000 BRL); median is ~86 BRL.

### Active customers (`active_customers`)
- Type: `simple`; unit: count
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, count(distinct customer_unique_id) filter (where is_revenue_order) as value from marts.fct_orders where true group by 1
  ```
- Must use customer_unique_id. customer_id is issued per order and over-counts people.
- Not additive across periods (a person active in two months counts once per month).
- Rejected alternative `active_customers_by_customer_id`: customer_id is generated per order, so one person can appear as many customers.

### Returning-customer share (`repeat_purchase_rate`)
- Type: `ratio`; unit: ratio
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, (count(distinct customer_unique_id) filter (where is_revenue_order and customer_purchase_day_number >= 2))::double / nullif(count(distinct customer_unique_id) filter (where is_revenue_order), 0) as value from marts.fct_orders where true group by 1
  ```
- Early months are mechanically low (nobody has history yet).
- Counting every 2nd+ order (incl. same-day baskets) gives 3.04% lifetime instead of 2.17%.
- Rejected alternative `repeat_rate_counting_same_day_orders`: 30% of "next orders" are placed the same day as the first (split baskets); they say nothing about loyalty and inflate the repeat rate by 40%.
- Rejected alternative `repeat_rate_by_customer_id`: Every customer_id has exactly one order, so the repeat rate is mechanically 0%.

### On-time delivery rate (`on_time_delivery_rate`)
- Type: `ratio`; unit: ratio
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, (count(*) filter (where is_delivered and days_late <= 0))::double / nullif(count(*) filter (where is_delivered), 0) as value from marts.fct_orders where true group by 1
  ```
- Comparing the delivery timestamp to the promised date at midnight would wrongly count same-day deliveries as late (see metric_conflicts report).
- Undelivered orders (shipped but never delivered) are excluded, which flatters the rate.
- The latest purchase months are right-censored (slow deliveries not in yet).
- Rejected alternative `on_time_rate_timestamp_compare`: The promise is a date (stored as 00:00:00); any delivery during the promised day would be counted late.
- Rejected alternative `on_time_rate_by_delivery_month`: Attributes a late order to the month it finally arrived, mixing several promise cohorts; ops accountability is by the month the promise was made.

### Avg delivery days (purchase -> customer) (`avg_delivery_days`)
- Type: `simple`; unit: days
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, avg(delivery_days) filter (where is_delivered) as value from marts.fct_orders where true group by 1
  ```
- Right-skewed (p99 ~ 46 days); report alongside the median in ops reviews.

### Avg promised days (`avg_promised_days`)
- Type: `simple`; unit: days
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, avg(promised_days) filter (where is_delivered) as value from marts.fct_orders where true group by 1
  ```

### Avg delivery vs promise (days, + = late) (`avg_days_vs_promise`)
- Type: `simple`; unit: days
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, avg(days_late) filter (where is_delivered) as value from marts.fct_orders where true group by 1
  ```
- {'A very negative value is not "good"': 'it means the promise is padded, which may cost conversion.'}

### Avg review score (1-5) (`avg_review_score`)
- Type: `simple`; unit: score
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, avg(review_score) filter (where is_revenue_order and review_score is not null) as value from marts.fct_orders where true group by 1
  ```
- 547 orders have more than one review row; the latest answered one is used.
- Survey is sent after delivery (or after the estimated date), so non-response is not random.

### Share of 5-star reviews (`pct_5_star`)
- Type: `ratio`; unit: ratio
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, (count(*) filter (where is_revenue_order and review_score = 5))::double / nullif(count(*) filter (where is_revenue_order and review_score is not null), 0) as value from marts.fct_orders where true group by 1
  ```

### Share of 1-2 star reviews (`pct_1_2_star`)
- Type: `ratio`; unit: ratio
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, (count(*) filter (where is_revenue_order and review_score <= 2))::double / nullif(count(*) filter (where is_revenue_order and review_score is not null), 0) as value from marts.fct_orders where true group by 1
  ```

### NPS-style score (`nps_style_score`)
- Type: `derived`; unit: points
- Formula: `(pct_5_star - pct_1_2_star) * 100`
- Not comparable to published NPS benchmarks.

### Freight / item price (`freight_to_price_ratio`)
- Type: `ratio`; unit: ratio
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, (sum(freight_brl) filter (where is_revenue_order))::double / nullif(sum(items_price_brl) filter (where is_revenue_order), 0) as value from marts.fct_orders where true group by 1
  ```
- The unweighted mean of per-order ratios is much higher (cheap items carry heavy freight).

### Cancellation rate (`cancellation_rate`)
- Type: `ratio`; unit: ratio
- Compiled SQL (monthly):

  ```sql
  select cast(date_trunc('month', purchase_date) as date) as period, (count(*) filter (where order_status in ('canceled', 'unavailable')))::double / nullif(count(*) filter (where true), 0) as value from marts.fct_orders where true group by 1
  ```
- "unavailable" = seller could not fulfil; grouped with canceled because neither became revenue.

### Top-10% sellers' share of GMV (`seller_top10pct_gmv_share`)
- Type: `concentration`; unit: ratio
- Compiled SQL (monthly):

  ```sql
  with e as (select cast(date_trunc('month', purchase_date) as date) as period, seller_id as entity, sum(price_brl) filter (where is_revenue_order) as v from marts.fct_order_items where true group by 1, 2), r as (select *, row_number() over (partition by period order by v desc, entity) as rk, count(*) over (partition by period) as n, sum(v) over (partition by period) as tot from e where v > 0) select period, sum(v) filter (where rk <= ceil(0.1 * n)) / any_value(tot) as value from r group by 1
  ```
- Depends on the number of active sellers in the period; compare like-for-like windows.

### Seller HHI (0-10,000) (`seller_hhi`)
- Type: `concentration`; unit: index
- Compiled SQL (monthly):

  ```sql
  with e as (select cast(date_trunc('month', purchase_date) as date) as period, seller_id as entity, sum(price_brl) filter (where is_revenue_order) as v from marts.fct_order_items where true group by 1, 2), s as (select *, sum(v) over (partition by period) as tot from e where v > 0) select period, sum(pow(100.0 * v / tot, 2)) as value from s group by 1
  ```
- < 1,500 = unconcentrated under US DoJ guidelines.
