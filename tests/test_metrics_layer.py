"""C1/C2: the metrics layer defines every required KPI and computes what hand SQL computes."""

import math

import duckdb
import pytest
from conftest import needs_warehouse

from marketplace.metrics import MetricsLayer
from marketplace.paths import WAREHOUSE

REQUIRED = {
    "gmv",
    "aov",
    "orders",
    "active_customers",
    "repeat_purchase_rate",
    "on_time_delivery_rate",
    "avg_days_vs_promise",
    "avg_review_score",
    "nps_style_score",
    "seller_top10pct_gmv_share",
    "seller_hhi",
    "freight_to_price_ratio",
    "cancellation_rate",
    "avg_delivery_days",
}

# Independent, hand-written SQL (does not use the compiler) for the full history.
HAND_SQL = {
    "gmv": "select sum(items_price_brl) from marts.fct_orders where is_revenue_order",
    "orders": "select count(*) from marts.fct_orders where is_revenue_order",
    "aov": "select sum(items_price_brl) / count(*) from marts.fct_orders where is_revenue_order",
    "active_customers": "select count(distinct customer_unique_id) from marts.fct_orders where is_revenue_order",
    "repeat_purchase_rate": """select count(distinct case when customer_order_number >= 2 then customer_unique_id end)::double
        / count(distinct customer_unique_id) from marts.fct_orders where is_revenue_order""",
    "on_time_delivery_rate": "select avg(case when days_late <= 0 then 1.0 else 0 end) from marts.fct_orders where is_delivered",
    "avg_delivery_days": "select avg(delivery_days) from marts.fct_orders where is_delivered",
    "avg_days_vs_promise": "select avg(days_late) from marts.fct_orders where is_delivered",
    "avg_review_score": "select avg(review_score) from marts.fct_orders where is_revenue_order",
    "nps_style_score": """select 100 * (avg(case when review_score = 5 then 1.0 else 0 end)
        - avg(case when review_score <= 2 then 1.0 else 0 end))
        from marts.fct_orders where is_revenue_order and review_score is not null""",
    "freight_to_price_ratio": "select sum(freight_brl) / sum(items_price_brl) from marts.fct_orders where is_revenue_order",
    "cancellation_rate": "select avg(case when order_status in ('canceled','unavailable') then 1.0 else 0 end) from marts.fct_orders",
    "seller_hhi": """with s as (select seller_id, sum(price_brl) v from marts.fct_order_items where is_revenue_order group by 1)
        select sum(pow(100 * v / (select sum(v) from s), 2)) from s""",
    "seller_top10pct_gmv_share": """with s as (select seller_id, sum(price_brl) v from marts.fct_order_items where is_revenue_order group by 1 having sum(price_brl) > 0),
        r as (select v, row_number() over (order by v desc) rk, count(*) over () n from s)
        select sum(v) filter (where rk <= ceil(0.1 * n)) / sum(v) from r""",
}


def test_catalog_complete():
    ml = MetricsLayer.load()
    assert set(ml.metrics) >= REQUIRED
    for name in REQUIRED:
        m = ml.metrics[name]
        for field in ("definition", "owner", "grain", "caveats", "unit", "label"):
            assert m.get(field) is not None, (name, field)


def test_rejected_alternatives_resolve():
    ml = MetricsLayer.load()
    for m in ml.metrics.values():
        for alt in m.get("rejected_alternatives", []):
            assert alt in ml.spec["rejected_alternatives"]


@needs_warehouse
@pytest.mark.parametrize("name", sorted(HAND_SQL))
def test_metric_equals_hand_sql(name):
    ml = MetricsLayer.load()
    got = ml.value(name)
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        want = float(con.execute(HAND_SQL[name]).fetchone()[0])
    assert math.isclose(got, want, rel_tol=1e-9), (name, got, want)


@needs_warehouse
def test_components_add_up_to_metric():
    ml = MetricsLayer.load()
    for name in ("on_time_delivery_rate", "avg_review_score", "cancellation_rate"):
        c = ml.components(name, by="customer_state", grain="all")
        assert math.isclose(c.num.sum() / c.den.sum(), ml.value(name), rel_tol=1e-9)


@needs_warehouse
def test_filters_and_windows():
    ml = MetricsLayer.load()
    sp = ml.value("gmv", where={"customer_state": "SP"})
    total = ml.value("gmv")
    assert 0 < sp < total
    monthly = ml.compute(["gmv"], grain="month")["gmv"].sum()
    assert math.isclose(monthly, total, rel_tol=1e-9)
    with pytest.raises(ValueError):
        ml.value("gmv", where={"not_a_dimension": "x"})
