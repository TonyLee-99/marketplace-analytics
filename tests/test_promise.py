"""H2/H3: no leakage in the promise model; the simulator behaves sensibly."""

import pandas as pd

from marketplace.analysis.promise_policy import FEATURES, FORBIDDEN, simulate


def test_no_post_purchase_features():
    assert not set(FEATURES) & FORBIDDEN
    for f in FEATURES:
        for bad in ("deliver", "approved", "carrier", "review", "status", "late"):
            assert bad not in f, f


def _effects():
    bins = [
        "15+ days early",
        "8-14 early",
        "1-7 early",
        "on promised day",
        "1-3 late",
        "4-7 late",
        "8-14 late",
        "15+ late",
    ]
    eff = [0, 0, 0, 0, -1, -2, -2, -2]
    rows = [{"bin": b, "effect": e} for b, e in zip(bins, eff, strict=True)]
    rep = {"fe_lpm": {"estimate": -0.01, "ci95": [-0.02, 0.0]}}
    return {"fe_plus_delivery_days": rows, "low_review_fe_plus_delivery_days": rows}, rep


def _orders():
    return pd.DataFrame(
        {
            "y": [5.0, 10.0, 20.0, 8.0],
            "olist_promised_days": [20, 20, 25, 6],
            "is_first_order": [True, True, False, True],
            "items_price_brl": [100.0, 50.0, 80.0, 70.0],
            "purchase_date": pd.to_datetime(["2018-04-01"] * 4),
        }
    )


def test_keeping_current_promise_changes_nothing():
    eff, rep = _effects()
    te = _orders()
    r = simulate(te, te["olist_promised_days"].to_numpy(), eff, rep)
    assert r["delta_late_pp"] == 0 and r["expected_delta_avg_review"] == 0


def test_shorter_promise_raises_late_rate_and_costs_reviews():
    eff, rep = _effects()
    te = _orders()
    r = simulate(te, te["y"].to_numpy() - 1, eff, rep)  # every order 1 day late
    assert r["late_rate"] == 1.0
    assert r["expected_delta_avg_review"] < 0
    assert r["mean_days_saved_vs_current"] > 0
