"""Golden tests: headline numbers recomputed straight from the raw CSV files (no dbt, no
marts, no metrics layer) must equal what the metrics layer reports."""

import math

import duckdb
import pytest
from conftest import needs_warehouse

from marketplace.metrics import MetricsLayer
from marketplace.paths import RAW

pytestmark = [needs_warehouse, pytest.mark.skipif(not (RAW / "olist_orders_dataset.csv").exists(),
                                                  reason="raw CSVs not downloaded")]


@pytest.fixture(scope="module")
def raw():
    con = duckdb.connect()
    for name, f in {"o": "olist_orders_dataset", "i": "olist_order_items_dataset",
                    "c": "olist_customers_dataset", "r": "olist_order_reviews_dataset"}.items():
        con.execute(f"create view {name} as select * from read_csv_auto('{RAW / (f + '.csv')}')")
    con.execute("""create view rev as
        select o.*, c.customer_unique_id, s.price from o join c using (customer_id)
        join (select order_id, sum(price) price from i group by 1) s using (order_id)
        where o.order_status not in ('canceled', 'unavailable')""")
    yield con
    con.close()


def test_gmv_and_orders(raw):
    ml = MetricsLayer.load()
    gmv, n = raw.execute("select sum(price), count(*) from rev").fetchone()
    assert math.isclose(ml.value("gmv"), gmv, rel_tol=1e-9)
    assert ml.value("orders") == n


def test_on_time_rate_date_compare(raw):
    v = raw.execute("""select avg(case when cast(order_delivered_customer_date as date)
                                        <= cast(order_estimated_delivery_date as date) then 1.0 else 0 end)
                       from o where order_status = 'delivered' and order_delivered_customer_date is not null""").fetchone()[0]
    assert math.isclose(MetricsLayer.load().value("on_time_delivery_rate"), v, rel_tol=1e-9)


def test_repeat_rate_distinct_days(raw):
    v = raw.execute("""with p as (select customer_unique_id, count(distinct cast(order_purchase_timestamp as date)) d
                                  from rev group by 1)
                       select avg(case when d >= 2 then 1.0 else 0 end) from p""").fetchone()[0]
    assert math.isclose(MetricsLayer.load().value("repeat_purchase_rate"), v, rel_tol=1e-9)
