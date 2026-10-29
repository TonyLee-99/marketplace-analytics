"""Metric governance: show where plausible definitions of the "same" KPI disagree.

For each governed metric that lists rejected alternatives in metrics.yml, compute both on
the real data and report the gap. Output: reports/metric_conflicts.json

    python -m marketplace.metric_conflicts
"""

from __future__ import annotations

import json
import sys

import duckdb

from marketplace.metrics import MetricsLayer
from marketplace.paths import REPORTS, WAREHOUSE

YOY_2017 = ("2017-01-01", "2017-08-31")
YOY_2018 = ("2018-01-01", "2018-08-31")


def _scalar(con, sql: str) -> float:
    return float(con.execute(sql).fetchone()[0])


def gmv_conflicts(con, ml: MetricsLayer) -> dict:
    variants = {
        "governed: item price, revenue orders": "sum(items_price_brl) filter (where is_revenue_order)",
        "incl. freight": "sum(items_total_brl) filter (where is_revenue_order)",
        "incl. canceled/unavailable": "sum(items_price_brl)",
        "payment-based": "sum(payment_total_brl) filter (where is_revenue_order)",
    }
    out = {}
    for label, expr in variants.items():
        total = _scalar(con, f"select {expr} from marts.fct_orders")
        a = _scalar(
            con,
            f"select {expr} from marts.fct_orders where purchase_date between "
            f"'{YOY_2017[0]}' and '{YOY_2017[1]}'",
        )
        b = _scalar(
            con,
            f"select {expr} from marts.fct_orders where purchase_date between "
            f"'{YOY_2018[0]}' and '{YOY_2018[1]}'",
        )
        out[label] = {"total_brl": round(total, 2), "yoy_jan_aug_growth": round(b / a - 1, 4)}
    governed = ml.value("gmv")
    assert abs(governed - out["governed: item price, revenue orders"]["total_brl"]) < 0.01
    spread = [v["total_brl"] for v in out.values()]
    return {
        "variants": out,
        "max_minus_min_total_brl": round(max(spread) - min(spread), 2),
        "resolution": "metrics.yml `gmv`: item price only, revenue orders, purchase-date. "
        "Freight and instalment interest are tracked as separate metrics.",
    }


def customer_id_conflicts(con, ml: MetricsLayer) -> dict:
    by_customer_id = _scalar(
        con, "select count(distinct customer_id) from marts.fct_orders where is_revenue_order"
    )
    repeat_by_customer_id = _scalar(
        con,
        """
        with c as (select customer_id, count(*) n from marts.fct_orders
                   where is_revenue_order group by 1)
        select avg(case when n >= 2 then 1.0 else 0 end) from c
        """,
    )
    lifetime_repeat_people = _scalar(
        con,
        "select avg(case when n_revenue_orders >= 2 then 1.0 else 0 end) "
        "from marts.dim_customers where n_revenue_orders >= 1",
    )
    return {
        "active_customers_all_time": {
            "governed_customer_unique_id": ml.value("active_customers"),
            "rejected_customer_id": by_customer_id,
            "overcount_pct": round(by_customer_id / ml.value("active_customers") - 1, 4),
        },
        "repeat_rate": {
            "governed_lifetime_share_of_people_with_2plus_orders": round(lifetime_repeat_people, 4),
            "rejected_customer_id_based": round(repeat_by_customer_id, 4),
            "governed_returning_customer_share_all_time": round(
                ml.value("repeat_purchase_rate"), 4
            ),
        },
        "resolution": "metrics.yml pins every customer metric to customer_unique_id; "
        "dim_customers is built at that grain.",
    }


def on_time_conflicts(con, ml: MetricsLayer) -> dict:
    governed = ml.value("on_time_delivery_rate")
    ts_compare = _scalar(
        con,
        "select avg(case when delivered_to_customer_at <= cast(estimated_delivery_date "
        "as timestamp) then 1.0 else 0 end) from marts.fct_orders where is_delivered",
    )
    monthly = con.execute(
        """
        with p as (
            select purchase_month m, avg(case when days_late <= 0 then 1.0 else 0 end) r,
                   count(*) n
            from marts.fct_orders where is_delivered group by 1),
        d as (
            select cast(date_trunc('month', delivered_to_customer_at) as date) m,
                   avg(case when days_late <= 0 then 1.0 else 0 end) r, count(*) n
            from marts.fct_orders where is_delivered group by 1)
        select p.m, p.r purchase_cohort_rate, d.r delivery_month_rate, p.n, d.n
        from p join d using (m)
        where p.m between '2017-01-01' and '2018-08-01'
        order by abs(p.r - d.r) desc
        """
    ).fetchall()
    worst = [
        {
            "month": str(r[0]),
            "purchase_cohort_on_time": round(r[1], 4),
            "delivery_month_on_time": round(r[2], 4),
            "gap_pp": round(100 * (r[1] - r[2]), 2),
            "orders_purchase_cohort": r[3],
            "orders_delivery_month": r[4],
        }
        for r in monthly[:3]
    ]
    return {
        "all_time": {
            "governed_date_compare": round(governed, 4),
            "rejected_timestamp_compare": round(ts_compare, 4),
            "gap_pp": round(100 * (governed - ts_compare), 2),
        },
        "largest_monthly_gaps_purchase_vs_delivery_month": worst,
        "resolution": "metrics.yml `on_time_delivery_rate`: date-level comparison, attributed "
        "to the purchase month (the month the promise was made).",
    }


def main() -> int:
    ml = MetricsLayer.load()
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    report = {
        "gmv": gmv_conflicts(con, ml),
        "customer_identity": customer_id_conflicts(con, ml),
        "on_time_delivery": on_time_conflicts(con, ml),
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "metric_conflicts.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
