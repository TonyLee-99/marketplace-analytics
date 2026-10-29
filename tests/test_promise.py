"""Promise model: no post-purchase features, no temporal leakage, sane simulator."""

import numpy as np
import pandas as pd

from marketplace.analysis.promise_policy import (
    FEATURES,
    FORBIDDEN,
    add_prior_history,
    simulate,
    train_rows,
)


def test_no_post_purchase_features():
    assert not set(FEATURES) & FORBIDDEN


def _toy():
    t = pd.Timestamp
    return pd.DataFrame({
        "primary_seller_id": ["s"] * 4,
        "lane": ["SP>RJ"] * 4,
        "purchased_at": [t("2018-01-01"), t("2018-01-05"), t("2018-01-10"), t("2018-01-20")],
        "delivered_to_customer_at": [t("2018-01-04"), t("2018-01-25"), t("2018-01-15"), t("2018-01-30")],
        "y": [3.0, 20.0, 5.0, 10.0],
    })


def test_history_uses_only_deliveries_before_purchase():
    h = add_prior_history(_toy()).set_index("purchased_at")
    # order of 2018-01-10: only the 01-04 delivery is known (the 01-05 order arrives 01-25)
    assert h.loc["2018-01-10", "seller_prior_n"] == 1
    assert h.loc["2018-01-10", "seller_prior_mean_days"] == 3.0
    # order of 2018-01-20: deliveries of 01-04 and 01-15 are known, never its own label
    assert h.loc["2018-01-20", "seller_prior_n"] == 2
    assert h.loc["2018-01-20", "seller_prior_mean_days"] == 4.0
    assert h.loc["2018-01-01", "seller_prior_n"] == 0


def test_future_label_change_does_not_move_features():
    a = add_prior_history(_toy())
    b = _toy()
    b.loc[3, "y"] = 999.0  # the last order's label (delivered after everyone's purchase)
    b.loc[1, "y"] = 999.0  # delivered 01-25: after the 01-10 and 01-20 purchases
    b = add_prior_history(b)
    for col in ("seller_prior_mean_days", "lane_prior_mean_days"):
        assert np.allclose(a[col].fillna(-1), b[col].fillna(-1))


def test_training_rows_are_known_before_month_start():
    t = pd.Timestamp
    d = pd.DataFrame({"pm": pd.PeriodIndex(["2018-01", "2018-01", "2018-02"], freq="M"),
                      "delivered_to_customer_at": [t("2018-02-20"), t("2018-03-05"), t("2018-02-25")]})
    rows = train_rows(d, pd.Period("2018-03", "M"), 3)
    assert (rows.delivered_to_customer_at < t("2018-03-01")).all()
    assert len(rows) == 1  # the Feb purchase is M-1 (excluded), the 03-05 delivery is unknown


def _effects():
    bins = ["15+ days early", "8-14 early", "1-7 early", "on promised day", "1-3 late", "4-7 late",
            "8-14 late", "15+ late"]
    rows = [{"bin": b, "effect": e} for b, e in zip(bins, [0, 0, 0, 0, -1, -2, -2, -2], strict=True)]
    return {"survey_today": (rows, rows)}, {"fe_lpm": {"estimate": -0.01, "ci95": [-0.02, 0.0]}}


def _orders():
    return pd.DataFrame({"y_eval": [5.0, 10.0, 20.0, 10_000.0], "olist_promised_days": [20, 20, 25, 20],
                         "is_delivered": [True, True, True, False], "is_first_order": [True] * 4,
                         "items_price_brl": [100.0, 50.0, 80.0, 70.0]})


def test_current_promise_changes_nothing_and_never_delivered_is_late():
    eff, rep = _effects()
    te = _orders()
    r = simulate(te, te["olist_promised_days"].to_numpy(), eff, -10.0, rep, 1)
    assert r["delta_late_pp"] == 0 and r["survey_today"]["expected_delta_avg_review"] == 0
    assert r["late_rate_current"] == 0.25  # the undelivered order counts as late


def test_shorter_promise_costs_reviews():
    eff, rep = _effects()
    te = _orders()
    r = simulate(te, te["y_eval"].clip(upper=30).to_numpy() - 1, eff, -10.0, rep, 1)
    assert r["late_rate"] == 1.0 and r["survey_today"]["expected_delta_avg_review"] < 0
