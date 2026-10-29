"""(c) Delivery experience -> customer outcomes, with causal designs.

Questions
  1. How much does a late delivery lower the review score / raise 1-2 star share?
  2. Does it lower repurchase?
  3. Is it *lateness versus the promise* that hurts, or slow delivery as such?

Designs (each with its assumptions written into the report):
  A. Naive comparison late vs on-time.
  B. OLS with fixed effects for seller, category, customer state and purchase month
     (+ log price, log freight, items, distance), SEs clustered by seller.
  C. Within seller-month: seller x purchase-month fixed effects -> compares the SAME seller's
     late vs on-time orders in the SAME month (absorbs seller quality and its drift).
  D. Same delivery time, different promise: control flexibly for actual delivery days, so the
     lateness coefficient is the "broken promise" effect (identifies what a promise policy
     changes).
  E. Regression-discontinuity-style comparison around the promised date (running variable =
     delivered date - promised date, cutoff between 0 and +1 days), local linear, several
     bandwidths, placebo cutoffs, density check.
  F. Dose-response: FE regression on 8 lateness bins.

Outputs reports/delivery_impact.json.  Run: python -m marketplace.analysis.delivery_impact
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pyfixest as pf

from marketplace.analysis.common import WINDOW_END, WINDOW_START, df, write_report
from marketplace.metrics import MetricsLayer

BINS = [
    ("15+ days early", -10_000, -15),
    ("8-14 early", -14, -8),
    ("1-7 early", -7, -1),
    ("on promised day", 0, 0),
    ("1-3 late", 1, 3),
    ("4-7 late", 4, 7),
    ("8-14 late", 8, 14),
    ("15+ late", 15, 10_000),
]
REF_BIN = "1-7 early"
FE_FULL = "primary_seller_id + primary_category + customer_state + purchase_month"
CONTROLS = "log_price + log_freight + n_items + log_km"
REPURCHASE_DAYS = 180


def lateness_bin(days_late: pd.Series) -> pd.Series:
    out = pd.Series(index=days_late.index, dtype="object")
    for label, lo, hi in BINS:
        out[(days_late >= lo) & (days_late <= hi)] = label
    return out


def load_orders() -> pd.DataFrame:
    d = df(
        f"""
        select order_id, customer_unique_id, primary_seller_id, primary_category,
               customer_state, lane, cast(purchase_month as varchar) as purchase_month,
               purchased_at, delivered_to_customer_at, review_score, days_late, is_late,
               delivery_days, promised_days, items_price_brl, freight_brl, n_items,
               coalesce(seller_customer_km, 0) as km, is_first_order
        from marts.fct_orders
        where is_revenue_order and is_delivered
          and purchase_date between '{WINDOW_START}' and '{WINDOW_END}'
        """
    )
    d["late"] = d["is_late"].astype(int)
    d["low_review"] = (d["review_score"] <= 2).astype(float)
    d.loc[d["review_score"].isna(), "low_review"] = np.nan
    d["log_price"] = np.log1p(d["items_price_brl"].astype(float))
    d["log_freight"] = np.log1p(d["freight_brl"].astype(float))
    d["log_km"] = np.log1p(d["km"].astype(float))
    d["bin"] = lateness_bin(d["days_late"])
    d["delivery_days_int"] = np.floor(d["delivery_days"]).clip(upper=60).astype(int)
    d["seller_month"] = d["primary_seller_id"] + "|" + d["purchase_month"]
    return d


def load_repurchase(orders: pd.DataFrame) -> pd.DataFrame:
    """First orders with a full 180-day observation window after delivery.

    Outcome = the person places another revenue order AFTER the first order was delivered
    and within 180 days of delivery. Orders placed before delivery cannot be caused by the
    delivery experience (many "repeat" orders are same-day split baskets), so they don't count.
    """
    nxt = df(
        """
        select f.order_id,
               min(o.purchased_at) as next_purchase_after_delivery
        from marts.fct_orders f
        join marts.fct_orders o
          on o.customer_unique_id = f.customer_unique_id
         and o.is_revenue_order and o.order_id <> f.order_id
         and o.purchased_at > f.delivered_to_customer_at
        where f.is_first_order and f.is_delivered
        group by 1
        """
    )
    first = orders[orders["is_first_order"]].merge(nxt, on="order_id", how="left")
    cutoff = pd.Timestamp(WINDOW_END) - pd.Timedelta(days=REPURCHASE_DAYS)
    first = first[first["delivered_to_customer_at"] <= cutoff].copy()
    gap = (first["next_purchase_after_delivery"] - first["delivered_to_customer_at"]).dt.days
    first["repurchased"] = (gap.notna() & (gap <= REPURCHASE_DAYS)).astype(float)
    return first


def coef(fit, name: str) -> dict:
    t = fit.tidy()
    r = t.loc[name]
    return {
        "estimate": float(r["Estimate"]),
        "se": float(r["Std. Error"]),
        "ci95": [float(r["2.5%"]), float(r["97.5%"])],
        "p": float(r["Pr(>|t|)"]),
        "n_obs": int(fit._N),
    }


def review_models(d: pd.DataFrame) -> dict:
    r = d.dropna(subset=["review_score"])
    vc = {"CRV1": "primary_seller_id"}
    naive = {
        "late_mean": float(r.loc[r.late == 1, "review_score"].mean()),
        "on_time_mean": float(r.loc[r.late == 0, "review_score"].mean()),
        "low_review_late": float(r.loc[r.late == 1, "low_review"].mean()),
        "low_review_on_time": float(r.loc[r.late == 0, "low_review"].mean()),
        "n_late": int((r.late == 1).sum()),
        "n_on_time": int((r.late == 0).sum()),
    }
    naive["diff"] = naive["late_mean"] - naive["on_time_mean"]
    out = {"naive": naive}
    out["B_fe_controls"] = coef(
        pf.feols(f"review_score ~ late + {CONTROLS} | {FE_FULL}", data=r, vcov=vc), "late"
    )
    out["B_fe_controls_low_review"] = coef(
        pf.feols(f"low_review ~ late + {CONTROLS} | {FE_FULL}", data=r, vcov=vc), "late"
    )
    out["C_within_seller_month"] = coef(
        pf.feols(
            f"review_score ~ late + {CONTROLS} | seller_month + primary_category + "
            "customer_state",
            data=r,
            vcov=vc,
        ),
        "late",
    )
    out["D_same_delivery_time"] = coef(
        pf.feols(
            f"review_score ~ late + {CONTROLS} | {FE_FULL} + delivery_days_int",
            data=r,
            vcov=vc,
        ),
        "late",
    )
    # Dose-response (F), with and without delivery-time control.
    r = r.copy()
    r["bin"] = pd.Categorical(r["bin"], categories=[b[0] for b in BINS])
    dr = {}
    specs = (
        ("fe", "review_score", ""),
        ("fe_plus_delivery_days", "review_score", " + delivery_days_int"),
        ("low_review_fe_plus_delivery_days", "low_review", " + delivery_days_int"),
    )
    for label, outcome, extra in specs:
        fit = pf.feols(
            f"{outcome} ~ i(bin, ref='{REF_BIN}') + {CONTROLS} | {FE_FULL}{extra}",
            data=r,
            vcov=vc,
        )
        t = fit.tidy()
        rows = []
        for b, _lo, _hi in BINS:
            n = int((r["bin"] == b).sum())
            raw = float(r.loc[r["bin"] == b, outcome].mean())
            if b == REF_BIN:
                rows.append({"bin": b, "effect": 0.0, "ci95": [0.0, 0.0], "n": n, "raw_mean": raw})
                continue
            key = f"bin::{b}"
            rows.append(
                {
                    "bin": b,
                    "effect": float(t.loc[key, "Estimate"]),
                    "ci95": [float(t.loc[key, "2.5%"]), float(t.loc[key, "97.5%"])],
                    "n": n,
                    "raw_mean": raw,
                }
            )
        dr[label] = rows
    out["F_dose_response"] = {"reference_bin": REF_BIN, **dr}
    return out


def rd_design(d: pd.DataFrame) -> dict:
    """Local-linear RD at the promised date. x = days_late, treated = x >= 1, cutoff 0.5."""
    r = d.dropna(subset=["review_score"]).copy()
    vc = {"CRV1": "primary_seller_id"}

    def fit_at(data, cutoff, h):
        s = data[(data.days_late > cutoff - h) & (data.days_late < cutoff + h)].copy()
        s["x"] = s["days_late"] - cutoff
        s["treat"] = (s["x"] > 0).astype(int)
        res = pf.feols("review_score ~ treat + x + x:treat", data=s, vcov=vc)
        c = coef(res, "treat")
        c["bandwidth_days"] = h
        return c

    main = [fit_at(r, 0.5, h) for h in (3, 5, 7, 10)]
    left = r[r.days_late <= 0]
    right = r[r.days_late >= 1]
    placebo = [
        {"cutoff": -4.5, **fit_at(left, -4.5, 4)},
        {"cutoff": -8.5, **fit_at(left, -8.5, 4)},
        {"cutoff": 4.5, **fit_at(right, 4.5, 4)},
    ]
    # Seller-FE version at h=5 (same seller, just-late vs just-on-time).
    s = r[(r.days_late > -4.5) & (r.days_late < 5.5)].copy()
    s["x"] = s["days_late"] - 0.5
    s["treat"] = (s["x"] > 0).astype(int)
    fe = coef(
        pf.feols("review_score ~ treat + x + x:treat | primary_seller_id", data=s, vcov=vc),
        "treat",
    )
    counts = r[(r.days_late >= -5) & (r.days_late <= 5)].groupby("days_late").size()
    means = r[(r.days_late >= -10) & (r.days_late <= 10)].groupby("days_late")["review_score"]
    return {
        "running_variable": "delivered date - promised date (days); treated = >= 1 day late",
        "local_linear": main,
        "with_seller_fe_h5": fe,
        "placebo_cutoffs": placebo,
        "density_counts_minus5_to_plus5": {int(k): int(v) for k, v in counts.items()},
        # A smooth density would give similar ratios across the cutoff; a much larger drop
        # from 0 to +1 than from -1 to 0 signals bunching before the promise date, which
        # weakens the RD "no manipulation" assumption.
        "density_ratio_0_over_minus1": float(counts[0] / counts[-1]),
        "density_ratio_plus1_over_0": float(counts[1] / counts[0]),
        "binned_means_minus10_to_plus10": {
            int(k): {"mean": float(v.mean()), "n": int(len(v))} for k, v in means
        },
        "assumptions": [
            "Potential review scores vary smoothly with delivery timing relative to the promise;"
            " only the 'promise broken' status jumps at the cutoff.",
            "No precise manipulation of the delivery date around the promise. CHECK FAILS "
            "PARTLY: counts drop much faster from 0 to +1 days than from -1 to 0 (see "
            "density ratios), consistent with carriers/sellers rushing to hit the promise. "
            "Treat the RD as suggestive; the within-seller-month and same-delivery-time "
            "designs carry the main conclusion.",
            "Running variable is discrete (whole days) so the estimate extrapolates the local "
            "linear fits half a day each side; standard errors clustered by seller.",
        ],
    }


def repurchase_models(d: pd.DataFrame) -> dict:
    f = load_repurchase(d)
    vc = {"CRV1": "primary_seller_id"}
    naive = {
        "rate_late": float(f.loc[f.late == 1, "repurchased"].mean()),
        "rate_on_time": float(f.loc[f.late == 0, "repurchased"].mean()),
        "n_late": int((f.late == 1).sum()),
        "n_on_time": int((f.late == 0).sum()),
    }
    naive["diff"] = naive["rate_late"] - naive["rate_on_time"]
    fe = coef(
        pf.feols(f"repurchased ~ late + {CONTROLS} | {FE_FULL}", data=f, vcov=vc), "late"
    )
    with_review = coef(
        pf.feols(
            f"repurchased ~ late + C(review_score) + {CONTROLS} | {FE_FULL}",
            data=f.dropna(subset=["review_score"]),
            vcov=vc,
        ),
        "late",
    )
    by_review = (
        f.dropna(subset=["review_score"])
        .groupby("review_score")["repurchased"]
        .agg(["mean", "size"])
        .reset_index()
        .rename(columns={"mean": "repurchase_rate", "size": "n"})
    )
    return {
        "definition": f"first orders delivered by {WINDOW_END} minus {REPURCHASE_DAYS} days; "
        f"outcome = another revenue order placed after delivery and within "
        f"{REPURCHASE_DAYS} days",
        "n_first_orders": int(len(f)),
        "base_rate": float(f["repurchased"].mean()),
        "naive": naive,
        "fe_lpm": fe,
        "fe_lpm_controlling_review": with_review,
        "repurchase_by_review_score": by_review,
    }


def impact_sizing(d: pd.DataFrame, review: dict, rep: dict) -> dict:
    """BRL at stake from late deliveries over the last 12 reliable months."""
    ml = MetricsLayer.load()
    last12 = d[(d.purchased_at >= "2017-09-01") & (d.purchased_at <= WINDOW_END)]
    late_orders = int(last12["late"].sum())
    late_first = int(((last12["late"] == 1) & last12["is_first_order"]).sum())
    aov = ml.value("aov", start="2017-09-01", end=WINDOW_END)
    eff = rep["fe_lpm"]
    lost_repurchases = -eff["estimate"] * late_first
    lo = -eff["ci95"][1] * late_first
    hi = -eff["ci95"][0] * late_first
    low_rev = review["B_fe_controls_low_review"]
    return {
        "window": f"2017-09-01..{WINDOW_END}",
        "late_orders": late_orders,
        "late_first_orders": late_first,
        "aov_brl": aov,
        "lost_repeat_orders_point": lost_repurchases,
        "lost_repeat_orders_ci95": [lo, hi],
        "lost_repeat_gmv_brl_point": lost_repurchases * aov,
        "lost_repeat_gmv_brl_ci95": [lo * aov, hi * aov],
        "extra_1_2_star_reviews_point": low_rev["estimate"] * late_orders,
        "extra_1_2_star_reviews_ci95": [
            low_rev["ci95"][0] * late_orders,
            low_rev["ci95"][1] * late_orders,
        ],
        "note": "Direct repeat-GMV loss only (one next order per lost repurchaser, valued at "
        "AOV). Excludes word-of-mouth, refunds and support cost, which Olist does not publish.",
    }


def main() -> int:
    d = load_orders()
    review = review_models(d)
    rd = rd_design(d)
    rep = repurchase_models(d)
    sizing = impact_sizing(d, review, rep)
    write_report(
        "delivery_impact",
        {
            "sample": {
                "delivered_revenue_orders": int(len(d)),
                "with_review": int(d["review_score"].notna().sum()),
                "late_share": float(d["late"].mean()),
                "window": f"{WINDOW_START}..{WINDOW_END}",
            },
            "review": review,
            "rd": rd,
            "repurchase": rep,
            "impact": sizing,
        },
    )
    print(
        f"review: naive {review['naive']['diff']:.3f}, FE {review['B_fe_controls']['estimate']:.3f}"
        f", seller-month {review['C_within_seller_month']['estimate']:.3f}, same-delivery-time "
        f"{review['D_same_delivery_time']['estimate']:.3f}; RD h=5 "
        f"{rd['local_linear'][1]['estimate']:.3f}"
    )
    print(
        f"repurchase: base {rep['base_rate']:.4f}, naive {rep['naive']['diff']:.4f}, "
        f"FE {rep['fe_lpm']['estimate']:.4f} {rep['fe_lpm']['ci95']}"
    )
    print(f"impact: {sizing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
