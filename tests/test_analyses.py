"""D1/H4/H6 checks on analysis logic and outputs."""

import json

import numpy as np
import pandas as pd
from conftest import needs_reports

from marketplace.analysis.cohorts import kaplan_meier
from marketplace.analysis.delivery_impact import BINS, lateness_bin
from marketplace.analysis.growth import decompose
from marketplace.paths import REPORTS


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


@needs_reports
def test_growth_report_residuals():
    g = json.loads((REPORTS / "growth.json").read_text())
    for r in g["mom"] + g["yoy"] + [g["ytd_jan_aug_2018_vs_2017"]]:
        assert abs(r["log_residual"]) < 1e-9


@needs_reports
def test_root_cause_effects_add_up():
    rc = json.loads((REPORTS / "root_cause.json").read_text())
    assert len(rc["moves"]) >= 2
    for m in rc["moves"]:
        for d in m["by_dimension"].values():
            if d["rate_effect"] is not None:
                # residual is computed at full precision before JSON rounding (6 dp)
                assert abs(d["residual"]) < 1e-9
                total = d["mix_effect"] + d["rate_effect"] + d["interaction"]
                assert abs(total - d["delta"]) < 5e-6


@needs_reports
def test_delivery_impact_has_causal_designs():
    di = json.loads((REPORTS / "delivery_impact.json").read_text())
    rv = di["review"]
    for k in ("B_fe_controls", "C_within_seller_month", "D_same_delivery_time"):
        assert rv[k]["ci95"][0] <= rv[k]["estimate"] <= rv[k]["ci95"][1]
    assert len(rv["F_dose_response"]["fe"]) >= 6
    assert len(di["rd"]["placebo_cutoffs"]) >= 2
