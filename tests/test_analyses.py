"""D1/H4/H6 checks on analysis logic and outputs."""

import numpy as np
import pandas as pd

from marketplace.analysis.cohorts import kaplan_meier
from marketplace.analysis.delivery_impact import BINS, lateness_bin
from marketplace.analysis.growth import decompose


def test_lmdi_decomposition_is_exact():
    g0 = pd.Series(
        {"gmv": 1000.0, "active_customers": 10.0, "orders_per_customer": 1.25, "aov": 80.0}
    )
    g1 = pd.Series(
        {"gmv": 1620.0, "active_customers": 15.0, "orders_per_customer": 1.2, "aov": 90.0}
    )
    r = decompose(g0, g1)
    assert abs(r["log_residual"]) < 1e-12
    assert abs(sum(d["contribution_brl"] for d in r["drivers"].values()) - 620.0) < 1e-9


def test_lateness_bins_cover_every_day():
    s = pd.Series(np.arange(-200, 200))
    b = lateness_bin(s)
    assert b.notna().all()
    assert set(b) == {x[0] for x in BINS}
    assert lateness_bin(pd.Series([0, 1, -1])).tolist() == [
        "on promised day",
        "1-3 late",
        "1-7 early",
    ]


def test_kaplan_meier_matches_hand_calculation():
    # 4 people: events at t=1 and t=3, censored at t=2 and t=4.
    km = kaplan_meier(np.array([1.0, 2.0, 3.0, 4.0]), np.array([1, 0, 1, 0]), [1, 3, 5])
    assert abs(km[1] - 0.25) < 1e-12  # S(1) = 3/4
    assert abs(km[3] - (1 - 0.75 * 0.5)) < 1e-12  # S(3) = 3/4 * 1/2


def test_synthetic_simpson_is_detected():
    """Both segments get worse, but volume moves to the better segment: the aggregate rises.
    The decomposition must show a negative rate effect and a positive total."""
    import pandas as pd

    from marketplace.analysis.root_cause import mix_rate_split

    seg = ["good", "bad"]
    d0, n0 = pd.Series([100, 900], seg), pd.Series([90, 450], seg)    # 90%, 50% -> 54%
    d1, n1 = pd.Series([900, 100], seg), pd.Series([765, 40], seg)    # 85%, 40% -> 80.5%
    r = mix_rate_split(n0, d0, n1, d1)
    delta = r["total1"] - r["total0"]
    assert delta > 0 and r["rate"].sum() < 0 and r["mix"].sum() > 0
    assert abs(r["mix"].sum() + r["rate"].sum() + r["inter"].sum() - delta) < 1e-12
