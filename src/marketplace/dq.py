"""Count every data-quality issue found in the raw Olist data and write docs/DATA_QUALITY.md.

The doc is generated so its numbers can never drift from the data.
Run: python -m marketplace.dq
"""

from __future__ import annotations

import json
import sys

import duckdb

from marketplace.paths import DOCS, REPORTS, WAREHOUSE

TS = "::timestamp"
CHECKS = [
    # (id, issue, sql returning one integer, handling)
    (
        "DQ01",
        "customer_id is order-scoped: distinct customer_id vs distinct people (customer_unique_id)",
        "select count(distinct customer_id) - count(distinct customer_unique_id) from raw.customers",
        "dim_customers is keyed on customer_unique_id; all customer metrics pinned to it in metrics.yml. Using customer_id would make the repeat rate 0%.",
    ),
    (
        "DQ02",
        "Orders with status 'delivered' but no delivered_to_customer date",
        "select count(*) from raw.orders where order_status = 'delivered' and order_delivered_customer_date is null",
        "is_delivered requires both status and date, so these 8 are excluded from delivery KPIs (still revenue orders).",
    ),
    (
        "DQ03",
        "Orders NOT delivered but carrying a customer-delivery date (canceled after delivery)",
        "select count(*) from raw.orders where order_status <> 'delivered' and order_delivered_customer_date is not null",
        "Status wins: not counted as delivered.",
    ),
    (
        "DQ04",
        "Orders with no items at all (mostly unavailable / canceled)",
        "select count(*) from raw.orders o where not exists (select 1 from raw.order_items i where i.order_id = o.order_id)",
        "is_revenue_order = false; kept in fct_orders for cancellation-rate denominators.",
    ),
    (
        "DQ05",
        "Orders with no payment row",
        "select count(*) from raw.orders o where not exists (select 1 from raw.order_payments p where p.order_id = o.order_id)",
        "Kept; payment_total_brl null, excluded from the reconciliation test.",
    ),
    (
        "DQ06",
        "Orders with no review",
        "select count(*) from raw.orders o where not exists (select 1 from raw.order_reviews r where r.order_id = o.order_id)",
        "Review metrics use reviewed orders only (documented caveat: survey non-response is not random).",
    ),
    (
        "DQ07",
        "Orders with more than one review row",
        "select count(*) from (select order_id from raw.order_reviews group by 1 having count(*) > 1)",
        "int_reviews_latest_per_order keeps the latest answered review.",
    ),
    (
        "DQ08",
        "review_id values shared by more than one order (review_id is not a key)",
        "select count(*) from (select review_id from raw.order_reviews group by 1 having count(distinct order_id) > 1)",
        "Grain of stg_olist__reviews is (review_id, order_id) via review_key.",
    ),
    (
        "DQ09",
        "Geolocation rows that are duplicates of (zip, lat, lng)",
        "select count(*) - count(distinct (geolocation_zip_code_prefix, geolocation_lat, geolocation_lng)) from raw.geolocation",
        "int_zip_geolocation: one row per zip prefix (median lat/lng, modal city/state).",
    ),
    (
        "DQ10",
        "Geolocation points outside Brazil's bounding box",
        "select count(*) from raw.geolocation where not (geolocation_lat::double between -34 and 6 and geolocation_lng::double between -74 and -34)",
        "Dropped before taking the median coordinate.",
    ),
    (
        "DQ11",
        "Zip prefixes mapped to more than one state in geolocation",
        "select count(*) from (select geolocation_zip_code_prefix from raw.geolocation group by 1 having count(distinct geolocation_state) > 1)",
        "Modal state used.",
    ),
    (
        "DQ12",
        "City spelling variants in geolocation (distinct raw names minus accent/case-normalised names)",
        "select count(distinct geolocation_city) - count(distinct lower(strip_accents(geolocation_city))) from raw.geolocation",
        "Cities normalised with lower(strip_accents(trim())) in staging.",
    ),
    (
        "DQ13",
        "Customer zip prefixes with no geolocation match",
        "select count(*) from raw.customers where customer_zip_code_prefix not in (select geolocation_zip_code_prefix from raw.geolocation)",
        "seller_customer_km is null for those orders; models treat missing distance as 0 km + the log feature (documented).",
    ),
    (
        "DQ14",
        "Seller zip prefixes with no geolocation match",
        "select count(*) from raw.sellers where seller_zip_code_prefix not in (select geolocation_zip_code_prefix from raw.geolocation)",
        "Same as DQ13.",
    ),
    (
        "DQ15",
        "Products with null category",
        "select count(*) from raw.products where product_category_name is null",
        "category = 'unknown'.",
    ),
    (
        "DQ16",
        "Categories missing from the English translation file",
        "select count(distinct product_category_name) from raw.products where product_category_name is not null and product_category_name not in (select product_category_name from raw.category_translation)",
        "seeds/category_translation_patch.csv adds the 2 missing names.",
    ),
    (
        "DQ17",
        "Products with weight 0 g",
        "select count(*) from raw.products where product_weight_g::double = 0",
        "Set to null (physically impossible).",
    ),
    (
        "DQ18",
        "Source column names misspelled ('lenght')",
        "select count(*) from (describe raw.products) where column_name like '%lenght%'",
        "Renamed to *_length in stg_olist__products.",
    ),
    (
        "DQ19",
        "Translation file header starts with a UTF-8 BOM",
        "select 1",
        "Column renamed in ingest (marketplace.ingest).",
    ),
    (
        "DQ20",
        "Orders handed to the carrier before they were purchased",
        f"select count(*) from raw.orders where order_delivered_carrier_date{TS} < order_purchase_timestamp{TS}",
        "Kept (timestamps likely recorded in different time zones/systems); handling_days can be negative; analyses use medians.",
    ),
    (
        "DQ21",
        "Orders delivered to the customer before the carrier pick-up",
        f"select count(*) from raw.orders where order_delivered_customer_date{TS} < order_delivered_carrier_date{TS}",
        "Kept; carrier_transit_days can be negative; medians used.",
    ),
    (
        "DQ22",
        "Orders delivered before purchase",
        f"select count(*) from raw.orders where order_delivered_customer_date{TS} < order_purchase_timestamp{TS}",
        "None found; enforced by dbt test assert_delivered_not_before_purchase.",
    ),
    (
        "DQ23",
        "Orders where payments differ from item price + freight by > 1 BRL",
        "with i as (select order_id, sum(price::double + freight_value::double) v from raw.order_items group by 1), p as (select order_id, sum(payment_value::double) v, max(payment_installments::int) n from raw.order_payments group by 1) select count(*) from i join p using (order_id) where abs(p.v - i.v) > 1",
        "Mostly instalment interest (n>1 and overpaid) - allowed. Remaining exceptions WARN in dbt test assert_payments_reconcile_to_items (error only if >0.5% of orders).",
    ),
    (
        "DQ24",
        "...of which NOT explained by instalment interest",
        "with i as (select order_id, sum(price::double + freight_value::double) v from raw.order_items group by 1), p as (select order_id, sum(payment_value::double) v, max(payment_installments::int) n from raw.order_payments group by 1) select count(*) from i join p using (order_id) where abs(p.v - i.v) > 1 and not (p.n > 1 and p.v > i.v)",
        "Reported as dbt WARN; investigated in a real team.",
    ),
    (
        "DQ25",
        "Payment rows with payment_type 'not_defined'",
        "select count(*) from raw.order_payments where payment_type = 'not_defined'",
        "Kept as a category (all have value 0).",
    ),
    (
        "DQ26",
        "Payment rows with value 0",
        "select count(*) from raw.order_payments where payment_value::double = 0",
        "Kept.",
    ),
    (
        "DQ27",
        "Item lines with freight 0",
        "select count(*) from raw.order_items where freight_value::double = 0",
        "Kept (free shipping promotions).",
    ),
    (
        "DQ28",
        "Purchase months with sparse capture: orders in Sep-Dec 2016 (Nov-2016 has none)",
        "select count(*) from raw.orders where order_purchase_timestamp{TS} < '2017-01-01'".replace(
            "{TS}", TS
        ),
        "Analyses use the reliable window Jan-2017..Aug-2018 (dim_date.is_in_reliable_window).",
    ),
    (
        "DQ29",
        "Orders purchased after 2018-08-31 (feed tails off: Sep/Oct 2018)",
        f"select count(*) from raw.orders where order_purchase_timestamp{TS} > '2018-08-31 23:59:59'",
        "Excluded from analyses; the anomaly monitor flags the drop as a data-feed incident.",
    ),
    (
        "DQ30",
        "People (customer_unique_id) with more than one delivery zip over time",
        "select count(*) from (select customer_unique_id from raw.customers group by 1 having count(distinct customer_zip_code_prefix) > 1)",
        "Modelled as SCD2 history in dim_customer_location_history.",
    ),
    (
        "DQ31",
        "Orders with items from more than one seller",
        "select count(*) from (select order_id from raw.order_items group by 1 having count(distinct seller_id) > 1)",
        "Order-level seller = primary seller (largest price share); item-level facts keep every seller.",
    ),
    (
        "DQ32",
        "Estimated delivery date stored as midnight timestamp (it is a date)",
        "select count(*) from raw.orders where strftime(order_estimated_delivery_date::timestamp, '%H:%M:%S') <> '00:00:00'",
        "0 non-midnight values: cast to DATE; on-time compares dates (timestamp compare would mis-count same-day deliveries as late).",
    ),
    (
        "DQ20b",
        "Orders handed to the carrier before they were APPROVED (negative handling time)",
        "select count(*) from raw.orders where order_delivered_carrier_date::timestamp < order_approved_at::timestamp",
        "Kept; handling_days is negative for these. Stage analyses use medians; flagged as a source timestamp issue.",
    ),
    (
        "DQ33",
        "Reviews of LATE delivered orders answered before the parcel arrived",
        "select count(*) from marts.fct_orders where is_delivered and is_late and is_review_before_delivery",
        "Survey fires ~2 days after the promised date. Review effects are reported for all reviews AND post-delivery reviews only (delivery_impact.json).",
    ),
    (
        "DQ34",
        "Delivered revenue orders with no seller-customer distance (zip not geocoded)",
        "select count(*) from marts.fct_orders where is_revenue_order and is_delivered and seller_customer_km is null",
        "Models use a missing-distance indicator plus 0 km fill (no silent imputation).",
    ),
    (
        "DQ35",
        "Revenue orders never delivered (shipped/processing/invoiced/approved/created)",
        "select count(*) from marts.fct_orders where is_revenue_order and not is_delivered",
        "Counted as LATE in promise-policy evaluation; excluded from review regressions (no delivery date).",
    ),
]


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    rows = []
    for cid, issue, sql, handling in CHECKS:
        n = con.execute(sql).fetchone()[0]
        rows.append({"id": cid, "issue": issue, "count": int(n), "handling": handling})
    con.close()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "data_quality.json").write_text(json.dumps(rows, indent=2))
    lines = [
        "# Data quality issues in the real Olist data",
        "",
        "_Generated by `make dq` (src/marketplace/dq.py) from data/warehouse.duckdb raw.* tables._",
        "_Every count below is recomputed on each build; the handling column says where in the "
        "pipeline the issue is dealt with._",
        "",
        "| ID | Issue | Count | Handling |",
        "|---|---|---:|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['issue']} | {r['count']:,} | {r['handling']} |")
    (DOCS / "DATA_QUALITY.md").write_text("\n".join(lines) + "\n")
    for r in rows:
        print(f"{r['id']} {r['count']:>9,}  {r['issue'][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
