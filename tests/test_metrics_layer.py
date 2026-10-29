"""C1/C2: the metrics layer defines every required KPI and computes what hand SQL computes."""

import math

import pytest
from conftest import needs_warehouse

from marketplace.metrics import MetricsLayer

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
def test_filters_and_windows():
    ml = MetricsLayer.load()
    sp = ml.value("gmv", where={"customer_state": "SP"})
    total = ml.value("gmv")
    assert 0 < sp < total
    monthly = ml.compute(["gmv"], grain="month")["gmv"].sum()
    assert math.isclose(monthly, total, rel_tol=1e-9)
    with pytest.raises(ValueError):
        ml.value("gmv", where={"not_a_dimension": "x"})
