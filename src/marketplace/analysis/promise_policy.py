"""Delivery-promise calibration (H1-H3).

1. Measure how padded Olist's promised delivery dates are (overall / lane / category).
2. Fit quantile models (P50/P80/P90) of delivery days using ONLY information available at
   checkout, evaluated out-of-time on purchases 2018-04..2018-08 (includes the May-2018
   truckers strike). Two designs:
     a) static split (diagnostic): train 2017-01..2018-01 (delivered by 2018-02-28),
        conformal calibration on 2018-02 (delivered by 2018-03-31), test 2018-04..08.
     b) rolling monthly retrain (production design, used for the policies): for each test
        month M, fit on purchases from the 6 months M-7..M-2 whose delivery was already
        recorded before M starts. Nothing from month M or later is ever used.
3. Simulate promise policies on the test set: days saved vs late-rate change, converted into
   expected review-score / 1-2-star impact with the *same-delivery-time* dose-response from
   delivery_impact (that is the effect of moving the promise while the parcel arrives when it
   arrives), plus repurchase GMV at risk and a conversion-benefit sensitivity.

Run: python -m marketplace.analysis.promise_policy
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from marketplace.analysis.common import WINDOW_END, df, read_report, write_report
from marketplace.analysis.delivery_impact import lateness_bin

TRAIN = ("2017-01-01", "2018-01-31", "2018-02-28")  # purchase from, to, delivered by
CAL = ("2018-02-01", "2018-02-28", "2018-03-31")
TEST = ("2018-04-01", WINDOW_END)
QUANTILES = (0.5, 0.8, 0.9)
MIN_LANE_N = 30

# Everything here is known when the customer clicks "buy". Anything after the purchase
# timestamp (approval, carrier hand-off, delivery, review, status) is deliberately absent.
CATEGORICAL = ["seller_state", "customer_state", "category_top", "purchase_dow"]
NUMERIC = [
    "log_km",
    "items_price_brl",
    "freight_brl",
    "n_items",
    "n_sellers",
    "weight_kg",
    "volume_l",
    "purchase_hour",
    "olist_promised_days",
    "seller_hist_median_days",
    "seller_hist_n",
    "lane_hist_median_days",
]
FEATURES = CATEGORICAL + NUMERIC
FORBIDDEN = {
    "approved_at",
    "delivered_to_carrier_at",
    "delivered_to_customer_at",
    "delivery_days",
    "days_late",
    "is_late",
    "review_score",
    "order_status",
}

# External assumption for the conversion benefit of a shorter promise (sensitivity only):
# Fisher, Gallino & Xu (2019, J. Marketing Research 56(5)) find +1.45% online sales per
# business day faster delivery (US apparel retailer). ~1.0% per calendar day after /1.4.
CONVERSION_LIFT_PER_DAY = (0.0025, 0.005, 0.010)


def load() -> pd.DataFrame:
    d = df(
        f"""
        with w as (
            select i.order_id,
                   sum(p.product_weight_g) / 1000.0 as weight_kg,
                   sum(p.product_volume_cm3) / 1000.0 as volume_l
            from marts.fct_order_items i join marts.dim_products p using (product_id)
            group by 1
        )
        select o.order_id, o.purchased_at, o.purchase_date, o.delivered_to_customer_at,
               o.primary_seller_id, o.primary_seller_state as seller_state,
               o.customer_state, o.lane, o.primary_category as category, o.n_items, o.n_sellers,
               o.items_price_brl::double as items_price_brl, o.freight_brl::double as freight_brl,
               o.seller_customer_km, o.promised_days as olist_promised_days,
               o.is_first_order, o.customer_unique_id,
               date_diff('day', o.purchase_date, cast(o.delivered_to_customer_at as date))
                   as delivered_day_number,
               w.weight_kg, w.volume_l
        from marts.fct_orders o left join w using (order_id)
        where o.is_revenue_order and o.is_delivered
          and o.purchase_date between '2017-01-01' and '{WINDOW_END}'
        """
    )
    d["log_km"] = np.log1p(d["seller_customer_km"])
    d["purchase_dow"] = d["purchased_at"].dt.dayofweek.astype(str)
    d["purchase_hour"] = d["purchased_at"].dt.hour
    d["y"] = d["delivered_day_number"].astype(float)
    return d


def split(d: pd.DataFrame):
    pdt, dlv = d["purchase_date"].astype("datetime64[ns]"), d["delivered_to_customer_at"]
    tr = d[(pdt >= TRAIN[0]) & (pdt <= TRAIN[1]) & (dlv <= TRAIN[2] + " 23:59:59")].copy()
    ca = d[(pdt >= CAL[0]) & (pdt <= CAL[1]) & (dlv <= CAL[2] + " 23:59:59")].copy()
    te = d[(pdt >= TEST[0]) & (pdt <= TEST[1])].copy()
    return tr, ca, te


def add_history_features(tr, *others):
    """Seller/lane history computed from the TRAIN period only (no look-ahead)."""
    seller = tr.groupby("primary_seller_id")["y"].agg(["median", "size"])
    lane = tr.groupby("lane")["y"].median()
    top_cats = tr["category"].value_counts().head(40).index
    out = []
    for frame in (tr, *others):
        f = frame.copy()
        f["seller_hist_median_days"] = f["primary_seller_id"].map(seller["median"])
        f["seller_hist_n"] = f["primary_seller_id"].map(seller["size"]).fillna(0)
        f["lane_hist_median_days"] = f["lane"].map(lane)
        f["category_top"] = np.where(f["category"].isin(top_cats), f["category"], "other")
        out.append(f)
    return out


def _encode(frames):
    """Map categoricals to integer codes using the union of train categories."""
    cats = {c: sorted(frames[0][c].astype(str).unique()) for c in CATEGORICAL}
    enc = []
    for f in frames:
        x = f[FEATURES].copy()
        for c in CATEGORICAL:
            x[c] = pd.Categorical(x[c].astype(str), categories=cats[c]).codes.astype(float)
            x.loc[x[c] < 0, c] = np.nan
        enc.append(x)
    return enc


def fit_quantile_models(tr, ca, te) -> dict:
    assert not (set(FEATURES) & FORBIDDEN), "leakage: post-purchase field in features"
    xtr, xca, xte = _encode([tr, ca, te])
    cat_mask = [c in CATEGORICAL for c in FEATURES]
    preds = {}
    for q in QUANTILES:
        m = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=q,
            max_iter=400,
            learning_rate=0.05,
            max_leaf_nodes=31,
            min_samples_leaf=50,
            categorical_features=cat_mask,
            random_state=7,
        )
        m.fit(xtr, tr["y"])
        p_ca, p_te = m.predict(xca), m.predict(xte)
        # Conformal adjustment (one-sided CQR) from the calibration month.
        scores = ca["y"].to_numpy() - p_ca
        n = len(scores)
        level = min(1.0, q * (1 + 1 / n))
        adj = float(np.quantile(scores, level, method="higher"))
        preds[q] = {"raw": p_te, "adj": adj, "conformal": p_te + adj}
    return preds


def pinball(y, p, q) -> float:
    e = y - p
    return float(np.mean(np.maximum(q * e, (q - 1) * e)))


def lane_quantile_policy(tr_ca: pd.DataFrame, te: pd.DataFrame, q: float) -> np.ndarray:
    lane = tr_ca.groupby("lane")["y"].agg(lambda s: np.quantile(s, q)).rename("lq")
    lane_n = tr_ca.groupby("lane").size()
    state = tr_ca.groupby("customer_state")["y"].agg(lambda s: np.quantile(s, q))
    glob = float(np.quantile(tr_ca["y"], q))
    lq = te["lane"].map(lane.where(lane_n >= MIN_LANE_N))
    lq = lq.fillna(te["customer_state"].map(state)).fillna(glob)
    return lq.to_numpy()


def padding_report(d: pd.DataFrame) -> dict:
    d = d.copy()
    d["padding"] = d["olist_promised_days"] - d["y"]
    qs = [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95]
    overall = {f"p{int(q * 100)}": float(np.quantile(d["padding"], q)) for q in qs}

    def grp(col, min_n):
        g = d.groupby(col).agg(
            n=("padding", "size"),
            median_padding=("padding", "median"),
            p10_padding=("padding", lambda s: np.quantile(s, 0.1)),
            median_promised=("olist_promised_days", "median"),
            median_actual=("y", "median"),
            late_rate=("padding", lambda s: float((s < 0).mean())),
        )
        return g[g.n >= min_n].sort_values("median_padding", ascending=False).reset_index()

    lanes = grp("lane", 200)
    cats = grp("category", 300)
    return {
        "definition": "padding = promised days - actual delivered day number (whole days; "
        "positive = arrived early)",
        "n_orders": int(len(d)),
        "overall_quantiles": overall,
        "mean_padding": float(d["padding"].mean()),
        "share_padded_over_7_days": float((d["padding"] > 7).mean()),
        "share_padded_over_14_days": float((d["padding"] > 14).mean()),
        "median_promised_days": float(d["olist_promised_days"].median()),
        "median_actual_days": float(d["y"].median()),
        "lanes_most_padded": lanes.head(10),
        "lanes_least_padded": lanes.tail(10),
        "n_lanes_with_200plus": int(len(lanes)),
        "categories_most_padded": cats.head(8),
        "categories_least_padded": cats.tail(8),
        "padding_histogram": d["padding"].clip(-20, 45).round().value_counts().sort_index(),
    }


def simulate(te: pd.DataFrame, promise_days: np.ndarray, effects: dict, rep: dict) -> dict:
    """Evaluate one promise policy on the test orders."""
    promise = np.ceil(np.asarray(promise_days, dtype=float)).clip(min=1)
    new_days_late = te["y"].to_numpy() - promise
    cur_days_late = te["y"].to_numpy() - te["olist_promised_days"].to_numpy()
    new_bin = lateness_bin(pd.Series(new_days_late, index=te.index))
    cur_bin = lateness_bin(pd.Series(cur_days_late, index=te.index))
    rev = {b["bin"]: b["effect"] for b in effects["fe_plus_delivery_days"]}
    low = {b["bin"]: b["effect"] for b in effects["low_review_fe_plus_delivery_days"]}
    d_review = (new_bin.map(rev) - cur_bin.map(rev)).to_numpy()
    d_low = (new_bin.map(low) - cur_bin.map(low)).to_numpy()
    late_new, late_cur = new_days_late > 0, cur_days_late > 0
    first = te["is_first_order"].to_numpy()
    extra_late_first = int((late_new & first).sum() - (late_cur & first).sum())
    months = te["purchase_date"].astype("datetime64[ns]").dt.to_period("M").nunique()
    annual = 12 / months
    aov = float(te["items_price_brl"].mean())
    rep_eff = rep["fe_lpm"]
    repurchase_loss = -rep_eff["estimate"] * extra_late_first * aov * annual
    days_saved = float(np.mean(te["olist_promised_days"].to_numpy() - promise))
    test_gmv_annual = float(te["items_price_brl"].sum()) * annual
    benefit = {
        f"{lift:.2%}_per_day": test_gmv_annual * lift * days_saved
        for lift in CONVERSION_LIFT_PER_DAY
    }
    return {
        "mean_promise_days": float(promise.mean()),
        "median_promise_days": float(np.median(promise)),
        "mean_days_saved_vs_current": days_saved,
        "late_rate": float(late_new.mean()),
        "late_rate_current": float(late_cur.mean()),
        "delta_late_pp": float(100 * (late_new.mean() - late_cur.mean())),
        "expected_delta_avg_review": float(np.mean(d_review)),
        "expected_delta_1_2_star_share_pp": float(100 * np.mean(d_low)),
        "extra_late_first_orders_test": extra_late_first,
        "repurchase_gmv_at_risk_brl_per_year": repurchase_loss,
        "repurchase_gmv_at_risk_brl_per_year_ci95": [
            -rep_eff["ci95"][1] * extra_late_first * aov * annual,
            -rep_eff["ci95"][0] * extra_late_first * aov * annual,
        ],
        "conversion_benefit_brl_per_year_sensitivity": benefit,
        "breakeven_conversion_lift_per_day": (
            repurchase_loss / (test_gmv_annual * days_saved) if days_saved > 0 else None
        ),
    }


WINDOW_CANDIDATES = (3, 6, 9)
# Training-window length is chosen on a BACKTEST period that ends before the test period.
BACKTEST = ("2017-10-01", "2018-03-31")


def rolling_predictions(d: pd.DataFrame, window: int, period=TEST) -> pd.DataFrame:
    """Rolling-origin monthly retrain. Returns rows of `period` with p50/p80/p90 + lane
    baselines; each month M is predicted by models fit on months M-window-1..M-2 using only
    orders already delivered before M starts."""
    d = d.copy()
    d["pm"] = d["purchase_date"].astype("datetime64[ns]").dt.to_period("M")
    out = []
    for month in pd.period_range(period[0], period[1], freq="M"):
        start = month.to_timestamp()
        lo, hi = month - (window + 1), month - 2
        tr = d[(d.pm >= lo) & (d.pm <= hi) & (d.delivered_to_customer_at < start)]
        te = d[d.pm == month]
        tr, te = add_history_features(tr, te)
        xtr, xte = _encode([tr, te])
        cat_mask = [c in CATEGORICAL for c in FEATURES]
        te = te.copy()
        for q in QUANTILES:
            m = HistGradientBoostingRegressor(
                loss="quantile",
                quantile=q,
                max_iter=400,
                learning_rate=0.05,
                max_leaf_nodes=31,
                min_samples_leaf=50,
                categorical_features=cat_mask,
                random_state=7,
            )
            m.fit(xtr, tr["y"])
            te[f"model_p{int(q * 100)}"] = m.predict(xte)
            te[f"lane_p{int(q * 100)}"] = lane_quantile_policy(tr, te, q)
        te["train_n"] = len(tr)
        te["train_window"] = f"{lo}..{hi}"
        out.append(te)
    return pd.concat(out)


def eval_quantiles(te: pd.DataFrame, cols: dict) -> dict:
    y = te["y"].to_numpy()
    res = {}
    for q in QUANTILES:
        tag = f"p{int(q * 100)}"
        r = {"target_coverage": q}
        for name, col in cols.items():
            p = te[col.format(tag)].to_numpy()
            r[f"{name}_coverage"] = float(np.mean(y <= np.ceil(p)))
            r[f"{name}_pinball"] = pinball(y, p, q)
        r["olist_estimate_pinball"] = pinball(y, te["olist_promised_days"].to_numpy(), q)
        res[tag] = r
    return res


def main() -> int:
    d = load()
    effects = read_report("delivery_impact")
    rev_effects, rep = effects["review"]["F_dose_response"], effects["repurchase"]
    # (a) static split: diagnostic only
    tr, ca, te_static = split(d)
    tr, ca, te_static = add_history_features(tr, ca, te_static)
    preds = fit_quantile_models(tr, ca, te_static)
    y_s = te_static["y"].to_numpy()
    static_eval = {}
    for q in QUANTILES:
        static_eval[f"p{int(q * 100)}"] = {
            "raw_coverage": float(np.mean(y_s <= np.ceil(preds[q]["raw"]))),
            "conformal_adjustment_days": preds[q]["adj"],
            "conformal_coverage": float(np.mean(y_s <= np.ceil(preds[q]["conformal"]))),
        }

    # (b) rolling monthly retrain: production design. Pick the window on the backtest.
    window_scores = {}
    for w in WINDOW_CANDIDATES:
        bt = rolling_predictions(d, w, BACKTEST)
        ev = eval_quantiles(bt, {"model": "model_{}"})
        window_scores[w] = {
            "mean_abs_coverage_error": float(
                np.mean([abs(v["model_coverage"] - v["target_coverage"]) for v in ev.values()])
            ),
            "mean_pinball": float(np.mean([v["model_pinball"] for v in ev.values()])),
        }
    window = min(window_scores, key=lambda w: window_scores[w]["mean_pinball"])
    te = rolling_predictions(d, window)
    model_eval = eval_quantiles(te, {"model": "model_{}", "lane_baseline": "lane_{}"})
    by_month = (
        te.assign(month=te["pm"].astype(str))
        .groupby("month")
        .apply(
            lambda g: pd.Series(
                {
                    "n": len(g),
                    "train_window": g["train_window"].iloc[0],
                    "train_n": int(g["train_n"].iloc[0]),
                    "p80_coverage": float(np.mean(g.y <= np.ceil(g.model_p80))),
                    "p90_coverage": float(np.mean(g.y <= np.ceil(g.model_p90))),
                    "median_actual": float(g.y.median()),
                    "mean_olist_promise": float(g.olist_promised_days.mean()),
                    "mean_model_p90": float(np.ceil(g.model_p90).mean()),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )

    current = te["olist_promised_days"].to_numpy().astype(float)
    policies = {
        "current_olist_estimate": current,
        "uniform_minus_5_days": current - 5,
        "lane_p80": te["lane_p80"].to_numpy(),
        "lane_p90": te["lane_p90"].to_numpy(),
        "model_p80": te["model_p80"].to_numpy(),
        "model_p90": te["model_p90"].to_numpy(),
        "model_p90_plus_2_days": te["model_p90"].to_numpy() + 2,
    }
    sims = {k: simulate(te, v, rev_effects, rep) for k, v in policies.items()}

    # Recommendation rule (written before looking at results): the shortest promise whose
    # simulated late rate stays at or below the on-time target (<= 7% late, i.e. >= 93%
    # on-time, metrics.yml) AND whose expected avg-review change is no worse than -0.05.
    eligible = {
        k: v
        for k, v in sims.items()
        if k != "current_olist_estimate"
        and v["late_rate"] <= 0.07
        and v["expected_delta_avg_review"] >= -0.05
    }
    rec = min(eligible, key=lambda k: eligible[k]["mean_promise_days"]) if eligible else None

    write_report(
        "promise_policy",
        {
            "padding": padding_report(d[d.purchase_date.astype("datetime64[ns]") >= "2017-01-01"]),
            "split": {
                "design": "rolling monthly retrain on months M-w-1..M-2, labels known before "
                "M starts; w chosen by lowest mean pinball loss on the backtest",
                "backtest_period": BACKTEST,
                "window_candidates": window_scores,
                "chosen_window_months": window,
                "test": {"purchases": TEST, "n": len(te)},
                "features": FEATURES,
                "forbidden_post_purchase_fields": sorted(FORBIDDEN),
            },
            "model_eval": model_eval,
            "model_eval_by_month": by_month,
            "static_split_diagnostic": {
                "train": {"purchases": TRAIN[:2], "delivered_by": TRAIN[2], "n": len(tr)},
                "calibration": {"purchases": CAL[:2], "delivered_by": CAL[2], "n": len(ca)},
                "test_n": len(te_static),
                "eval": static_eval,
                "lesson": "Delivery got much faster from Apr-2018 (median 13 -> 7-9 days). "
                "A model fit on 2017 and conformalised on Feb-2018 (a slow month) "
                "over-covers in the test period, so the promise must be retrained "
                "monthly.",
            },
            "policies": sims,
            "recommendation_rule": "shortest mean promise with late rate <= 7% and expected "
            "avg review change >= -0.05",
            "recommended_policy": rec,
            "conversion_assumption_source": "Fisher, Gallino & Xu (2019), The Value of Rapid "
            "Delivery in Omnichannel Retailing, J. Marketing Research 56(5): +1.45% online "
            "sales per business day faster delivery. Used only as a sensitivity range; Olist "
            "does not publish sessions/conversion, so the benefit is NOT measured here.",
            "test_lanes_for_dashboard": te.assign(
                p80=np.ceil(te["model_p80"]), p90=np.ceil(te["model_p90"])
            )
            .groupby("lane")
            .agg(
                n=("y", "size"),
                current=("olist_promised_days", "mean"),
                model_p80=("p80", "mean"),
                model_p90=("p90", "mean"),
                actual_median=("y", "median"),
                late_current=("olist_promised_days", lambda s: 0.0),
            )
            .query("n >= 100")
            .reset_index(),
        },
    )
    for k, v in sims.items():
        print(
            f"{k:<24} promise {v['mean_promise_days']:5.1f}d  saved {v['mean_days_saved_vs_current']:5.1f}d"
            f"  late {v['late_rate']:.3f} ({v['delta_late_pp']:+.1f}pp)  "
            f"review {v['expected_delta_avg_review']:+.3f}"
        )
    for k, v in model_eval.items():
        print(k, {kk: round(vv, 3) for kk, vv in v.items()})
    print(by_month.to_string())
    print("static:", static_eval)
    print("recommended:", rec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
