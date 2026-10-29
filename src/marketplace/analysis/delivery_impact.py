"""(c) Delivery experience -> customer outcomes.

The central measurement problem
-------------------------------
Olist sends the satisfaction survey about 2 days after the PROMISED date, whether or not the
parcel has arrived. So for late orders most reviews (70%) are written BEFORE delivery: the
customer is rating a parcel they do not have. Every review effect below is therefore
reported twice:
  * "recorded"      - all reviews: what the platform's star rating records under today's
                      survey rule (the right cost for displayed ratings);
  * "post-delivery" - only reviews answered after the parcel arrived: closer to satisfaction
                      with the delivered experience, but selected (angry customers answer
                      early), so it is a bound, not the effect.

Designs (assumptions are written into the report):
  A. naive late vs on-time
  B. OLS + fixed effects (seller, category, customer state, purchase month) + controls
  C. within seller x purchase month (same seller, same month)
  D. "same delivery time" (adds delivery-day FE). Caveat: conditions on delivery time, which
     is partly caused by the promise (bunching before the promise) -> mediator problem.
  E. carrier-leg lateness only: orders the seller handed over on time, within seller-month,
     post-delivery reviews (lateness comes from the carrier leg, not seller behaviour)
  F. exogenous shock: the May-2018 Brazilian truckers' strike (21-31 May) as an instrument
     for lateness, same lanes before/after, 2SLS
  G. dose-response by lateness bin (recorded and post-delivery)
  Appendix: why a regression discontinuity at the promise date FAILS here (manipulation +
  the survey-timing regime switches at the same cutoff). Not used as an estimate.

Run: python -m marketplace.analysis.delivery_impact
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
CONTROLS = "log_price + log_freight + n_items + log_km + km_missing"
REPURCHASE_DAYS = 180
VC = {"CRV1": "primary_seller_id"}
STRIKE = ("2018-05-14", "2018-05-27")  # purchases in transit during the 21-31 May strike
STRIKE_CONTROLS = [("2018-04-16", "2018-05-06"), ("2018-06-11", "2018-07-01")]


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
               purchase_date, purchased_at, delivered_to_customer_at, review_score,
               review_sent_at, is_review_before_delivery, is_late_handover,
               days_late, is_late, delivery_days, promised_days, carrier_transit_days,
               items_price_brl, freight_brl, n_items, seller_customer_km, is_first_order
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
    d["km_missing"] = d["seller_customer_km"].isna().astype(int)
    d["log_km"] = np.log1p(d["seller_customer_km"].fillna(0).astype(float))
    d["bin"] = lateness_bin(d["days_late"])
    d["delivery_days_int"] = np.floor(d["delivery_days"]).clip(upper=60).astype(int)
    d["seller_month"] = d["primary_seller_id"] + "|" + d["purchase_month"]
    d["post_delivery_review"] = d["is_review_before_delivery"].eq(False)
    return d


def coef(fit, name: str) -> dict:
    r = fit.tidy().loc[name]
    return {
        "estimate": float(r["Estimate"]),
        "se": float(r["Std. Error"]),
        "ci95": [float(r["2.5%"]), float(r["97.5%"])],
        "p": float(r["Pr(>|t|)"]),
        "n_obs": int(fit._N),
    }


def survey_timing(d: pd.DataFrame) -> dict:
    r = d.dropna(subset=["review_score"]).copy()
    r["sent_before"] = r["review_sent_at"] < r["delivered_to_customer_at"]
    by_late = r.groupby("is_late").agg(
        n=("review_score", "size"),
        sent_before_delivery=("sent_before", "mean"),
        answered_before_delivery=("is_review_before_delivery", "mean"),
        mean_score=("review_score", "mean"),
    )
    late = r[r.is_late]
    promise_date = pd.to_datetime(late["purchase_date"]) + pd.to_timedelta(late["promised_days"], "D")
    sent_vs_promise = (late["review_sent_at"].dt.normalize() - promise_date).dt.days.value_counts().sort_index()
    near = (
        r[(r.days_late >= -2) & (r.days_late <= 6)]
        .groupby("days_late")
        .agg(n=("review_score", "size"), score=("review_score", "mean"),
             sent_before=("sent_before", "mean"), answered_before=("is_review_before_delivery", "mean"))
    )
    split = r.groupby(["is_late", "is_review_before_delivery"])["review_score"].agg(["size", "mean"]).reset_index()
    return {
        "by_late": by_late.reset_index(),
        "late_answered_before_delivery_share": float(late["is_review_before_delivery"].mean()),
        "survey_sent_days_after_promise_for_late_orders": sent_vs_promise.head(12),
        "modal_send_day_after_promise": int(sent_vs_promise.idxmax()),
        "near_cutoff": near.reset_index(),
        "score_by_late_and_timing": split,
    }


def review_designs(r: pd.DataFrame) -> dict:
    """Designs A-D + dose-response on a review sample r."""
    out = {"naive": {
        "late_mean": float(r.loc[r.late == 1, "review_score"].mean()),
        "on_time_mean": float(r.loc[r.late == 0, "review_score"].mean()),
        "n_late": int((r.late == 1).sum()),
        "n_on_time": int((r.late == 0).sum()),
    }}
    out["naive"]["diff"] = out["naive"]["late_mean"] - out["naive"]["on_time_mean"]
    out["B_fe_controls"] = coef(pf.feols(f"review_score ~ late + {CONTROLS} | {FE_FULL}", data=r, vcov=VC), "late")
    out["B_fe_controls_low_review"] = coef(pf.feols(f"low_review ~ late + {CONTROLS} | {FE_FULL}", data=r, vcov=VC), "late")
    out["C_within_seller_month"] = coef(pf.feols(
        f"review_score ~ late + {CONTROLS} | seller_month + primary_category + customer_state", data=r, vcov=VC), "late")
    out["D_same_delivery_time"] = coef(pf.feols(
        f"review_score ~ late + {CONTROLS} | {FE_FULL} + delivery_days_int", data=r, vcov=VC), "late")
    rr = r.copy()
    rr["bin"] = pd.Categorical(rr["bin"], categories=[b[0] for b in BINS])
    dr = {}
    specs = (
        ("fe", "review_score", ""),
        ("fe_plus_delivery_days", "review_score", " + delivery_days_int"),
        ("low_review_fe", "low_review", ""),
        ("low_review_fe_plus_delivery_days", "low_review", " + delivery_days_int"),
    )
    for label, outcome, extra in specs:
        fit = pf.feols(f"{outcome} ~ i(bin, ref='{REF_BIN}') + {CONTROLS} | {FE_FULL}{extra}", data=rr, vcov=VC)
        t = fit.tidy()
        rows = []
        for b, _lo, _hi in BINS:
            n = int((rr["bin"] == b).sum())
            raw = float(rr.loc[rr["bin"] == b, outcome].mean()) if n else None
            k = f"bin::{b}"
            if b == REF_BIN or k not in t.index:
                rows.append({"bin": b, "effect": 0.0, "ci95": [0.0, 0.0], "n": n, "raw_mean": raw})
                continue
            rows.append({"bin": b, "effect": float(t.loc[k, "Estimate"]),
                         "ci95": [float(t.loc[k, "2.5%"]), float(t.loc[k, "97.5%"])], "n": n, "raw_mean": raw})
        dr[label] = rows
    out["G_dose_response"] = {"reference_bin": REF_BIN, **dr}
    return out


def carrier_leg_design(r_post: pd.DataFrame) -> dict:
    s = r_post[r_post["is_late_handover"].eq(False)]
    res = coef(pf.feols(f"review_score ~ late + {CONTROLS} | seller_month + primary_category + customer_state",
                        data=s, vcov=VC), "late")
    res["sample"] = ("post-delivery reviews of orders the seller handed to the carrier on time; "
                     "lateness comes from the carrier leg")
    res["late_share_in_sample"] = float(s["late"].mean())
    return res


def strike_iv(d: pd.DataFrame) -> dict:
    """2SLS: late instrumented by 'purchased in the week before / during the strike'."""
    pdt = pd.to_datetime(d["purchase_date"])
    win = ((pdt >= STRIKE[0]) & (pdt <= STRIKE[1])).to_numpy()
    ctl = np.zeros(len(d), dtype=bool)
    for a, b in STRIKE_CONTROLS:
        ctl |= ((pdt >= a) & (pdt <= b)).to_numpy()
    keep = (win | ctl) & d.review_score.notna().to_numpy()
    s = d[keep].copy()
    s["strike"] = win[keep].astype(int)
    out = {"strike_window_purchases": STRIKE, "control_windows": STRIKE_CONTROLS,
           "assumption": "Exclusion: the strike moved delivery times but did not change what customers "
           "think of the product or seller except through lateness. Same-lane comparison (lane FE) with "
           "category FE. Threats: strike-related stockouts and general mood; the post-delivery subsample is "
           "selected on answer timing."}
    s["pday"] = pd.to_datetime(s["purchase_date"]).dt.strftime("%Y-%m-%d")
    # Recorded stars, clustered by purchase day (right level for a time shock) + seller FE + AR set
    fs_day = coef(pf.feols(f"late ~ strike + {CONTROLS} | lane + primary_category", data=s,
                           vcov={"CRV1": "pday"}), "strike")
    iv_sfe = coef(pf.feols(f"review_score ~ {CONTROLS} | primary_seller_id + lane + primary_category | late ~ strike",
                           data=s, vcov={"CRV1": "lane"}), "late")
    acc = []
    for b0 in np.arange(-4.0, 1.001, 0.05):
        s["ytil"] = s["review_score"] - b0 * s["late"]
        t = pf.feols(f"ytil ~ strike + {CONTROLS} | lane + primary_category", data=s, vcov={"CRV1": "pday"}).tidy().loc["strike"]
        if t["Pr(>|t|)"] > 0.05:
            acc.append(float(round(b0, 2)))
    out["recorded_robustness"] = {
        "first_stage_F_day_clustered": float((fs_day["estimate"] / fs_day["se"]) ** 2),
        "iv_with_seller_fe": iv_sfe,
        "anderson_rubin_95_set_day_clustered": [min(acc), max(acc)] if acc else None,
        "mean_days_late_among_late_strike_vs_control": [
            float(s.loc[(s.strike == 1) & (s.late == 1), "days_late"].mean()),
            float(s.loc[(s.strike == 0) & (s.late == 1), "days_late"].mean())],
    }
    out["post_delivery_share_strike_vs_control"] = [float(s.loc[s.strike == 1, "post_delivery_review"].mean()),
                                                     float(s.loc[s.strike == 0, "post_delivery_review"].mean())]
    for label, sub in (("recorded_all_reviews", s), ("post_delivery_reviews", s[s.post_delivery_review])):
        vc = {"CRV1": "lane"}
        fs = pf.feols(f"late ~ strike + {CONTROLS} | lane + primary_category", data=sub, vcov=vc)
        rf = pf.feols(f"review_score ~ strike + {CONTROLS} | lane + primary_category", data=sub, vcov=vc)
        iv = pf.feols(f"review_score ~ {CONTROLS} | lane + primary_category | late ~ strike", data=sub, vcov=vc)
        f = coef(fs, "strike")
        out[label] = {
            "n": int(len(sub)),
            "late_rate_strike_window": float(sub.loc[sub.strike == 1, "late"].mean()),
            "late_rate_control_windows": float(sub.loc[sub.strike == 0, "late"].mean()),
            "first_stage": f,
            "first_stage_F": float((f["estimate"] / f["se"]) ** 2),
            "reduced_form": coef(rf, "strike"),
            "iv_late_effect": coef(iv, "late"),
        }
    out["post_delivery_reviews"]["status"] = ("INVALID: the strike itself shifts who answers after delivery "
                                              "(selection on a post-instrument variable). Not used as evidence.")
    return out


def rd_appendix(r: pd.DataFrame) -> dict:
    """Why a regression discontinuity at the promise date is not valid here."""

    def fit_at(data, cutoff, h):
        s = data[(data.days_late > cutoff - h) & (data.days_late < cutoff + h)].copy()
        s["x"] = s["days_late"] - cutoff
        s["treat"] = (s["x"] > 0).astype(int)
        c = coef(pf.feols("review_score ~ treat + x + x:treat", data=s, vcov=VC), "treat")
        c["bandwidth_days"] = h
        return c

    counts = r[(r.days_late >= -5) & (r.days_late <= 5)].groupby("days_late").size()
    return {
        "status": "NOT USED AS AN ESTIMATE",
        "why_it_fails": [
            "Compound treatment: at +1/+2 days the promise is broken AND the survey starts to be sent "
            "before delivery (see survey_timing.near_cutoff).",
            "Manipulation: deliveries bunch just before the promise (density ratios below).",
            "Bandwidth-sensitive estimates and a discrete running variable (whole days).",
            "A placebo cutoff at -4.5 days is significant.",
        ],
        "local_linear_by_bandwidth": [fit_at(r, 0.5, h) for h in (3, 5, 7, 10)],
        "placebo_cutoffs": [{"cutoff": c, **fit_at(r[r.days_late <= 0] if c < 0 else r[r.days_late >= 1], c, 4)}
                            for c in (-4.5, -8.5, 4.5)],
        "density_counts_minus5_to_plus5": {int(k): int(v) for k, v in counts.items()},
        "density_ratio_0_over_minus1": float(counts[0] / counts[-1]),
        "density_ratio_plus1_over_0": float(counts[1] / counts[0]),
        "binned_means_minus10_to_plus10": {
            int(k): {"mean": float(v.mean()), "n": int(len(v))}
            for k, v in r[(r.days_late >= -10) & (r.days_late <= 10)].groupby("days_late")["review_score"]
        },
    }


def load_repurchase(orders: pd.DataFrame) -> pd.DataFrame:
    """First orders with a full 180-day window after delivery. Outcome = another revenue
    order placed AFTER the first order was delivered and within 180 days of delivery."""
    nxt = df(
        """
        select f.order_id, min(o.purchased_at) as next_purchase_after_delivery
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


def repurchase_models(d: pd.DataFrame) -> dict:
    f = load_repurchase(d)
    naive = {"rate_late": float(f.loc[f.late == 1, "repurchased"].mean()),
             "rate_on_time": float(f.loc[f.late == 0, "repurchased"].mean()),
             "n_late": int((f.late == 1).sum()), "n_on_time": int((f.late == 0).sum())}
    naive["diff"] = naive["rate_late"] - naive["rate_on_time"]
    fe = coef(pf.feols(f"repurchased ~ late + {CONTROLS} | {FE_FULL}", data=f, vcov=VC), "late")
    base = float(f["repurchased"].mean())
    mde = 2.8 * fe["se"]  # 80% power, alpha 0.05, two-sided
    return {
        "definition": f"first orders delivered by {WINDOW_END} minus {REPURCHASE_DAYS} days; outcome = another "
        f"revenue order placed after delivery and within {REPURCHASE_DAYS} days",
        "n_first_orders": int(len(f)),
        "base_rate": base,
        "naive": naive,
        "fe_lpm": fe,
        "mde_80pct_power": mde,
        "mde_relative_to_base": mde / base,
        "ci_lower_relative_to_base": fe["ci95"][0] / base,
        "reading": "UNDERPOWERED: effects smaller than the MDE cannot be detected; the CI includes zero and "
        "also a large relative loss. Do not read as 'no effect'.",
    }


def impact_sizing(d: pd.DataFrame, rec: dict, post: dict, rep: dict) -> dict:
    """12-month sizing (Sep-2017..Aug-2018)."""
    ml = MetricsLayer.load()
    last12 = d[(d.purchased_at >= "2017-09-01") & (d.purchased_at <= WINDOW_END)]
    late_orders = int(last12["late"].sum())
    late_first = int(((last12["late"] == 1) & last12["is_first_order"]).sum())
    aov = ml.value("aov", start="2017-09-01", end=WINDOW_END)
    eff = rep["fe_lpm"]
    lost = -eff["estimate"] * late_first
    # Survey-on-confirmed-delivery lever: late orders reviewed before the parcel arrived get,
    # counterfactually, the score distribution of same-bin late orders reviewed after delivery.
    lr = last12[last12.late.eq(1) & last12.review_score.notna()]
    post_bin = lr[lr.post_delivery_review].groupby("bin").agg(score=("review_score", "mean"), low=("low_review", "mean"))
    pre = lr[~lr.post_delivery_review]
    cf_score = pre["bin"].map(post_bin["score"])
    cf_low = pre["bin"].map(post_bin["low"])
    n_reviews = int(last12.review_score.notna().sum())
    dlc = lr["days_late"].clip(upper=30)
    post_day = lr[lr.post_delivery_review].groupby(dlc[lr.post_delivery_review])["low_review"].mean()
    cf_exact = dlc[~lr.post_delivery_review].map(post_day)
    thin = lr[lr.post_delivery_review & lr["bin"].isin(["8-14 late", "15+ late"])].groupby("bin").size()
    return {
        "window": f"2017-09-01..{WINDOW_END}",
        "late_orders": late_orders,
        "late_first_orders": late_first,
        "aov_brl": aov,
        "lost_repeat_orders_point": lost,
        "lost_repeat_gmv_brl_point": lost * aov,
        "lost_repeat_gmv_brl_ci95": [-eff["ci95"][1] * late_first * aov, -eff["ci95"][0] * late_first * aov],
        "extra_1_2_star_reviews_recorded": rec["B_fe_controls_low_review"]["estimate"] * late_orders,
        "extra_1_2_star_reviews_post_delivery": post["B_fe_controls_low_review"]["estimate"] * late_orders,
        "survey_on_delivery_lever": {
            "late_reviews_answered_before_delivery": int(len(pre)),
            "one_two_star_reviews_avoided_upper_bound": float((pre["low_review"] - cf_low).sum()),
            "avg_star_gain_on_those_reviews": float((cf_score - pre["review_score"]).mean()),
            "network_avg_review_gain": float((cf_score - pre["review_score"]).sum() / n_reviews),
            "reviews_in_window": n_reviews,
            "one_two_star_avoided_exact_day_cells": float((pre["low_review"] - cf_exact).sum(skipna=True)),
            "pre_delivery_reviews_without_exact_day_match": int(cf_exact.isna().sum()),
            "post_delivery_reviews_in_8plus_day_bins": {str(k): int(v) for k, v in thin.items()},
            "pre_delivery_share_in_8plus_day_bins": float(pre["bin"].isin(["8-14 late", "15+ late"]).mean()),
            "framing": "Two instruments: keep a delivery-issue contact at promise + 2 days (incl. never-delivered "
            "orders, no public star) and move only the product/seller star rating to confirmed delivery. Value "
            "= rating accuracy for buyers and sellers; no BRL is claimed.",
            "note": "Upper bound: assumes pre-delivery reviewers would score like same-bin post-delivery "
            "reviewers once the parcel arrives (post-delivery reviewers are a selected, calmer group). "
            "Orders that never arrive are not in this sample.",
        },
    }


def main() -> int:
    d = load_orders()
    r_all = d.dropna(subset=["review_score"])
    r_post = r_all[r_all.post_delivery_review]
    timing = survey_timing(d)
    recorded = review_designs(r_all)
    post = review_designs(r_post)
    bounds = {k: {"recorded_all_reviews": recorded[k]["estimate"], "post_delivery_reviews": post[k]["estimate"]}
              for k in ("B_fe_controls", "C_within_seller_month", "D_same_delivery_time")}
    bounds["naive"] = {"recorded_all_reviews": recorded["naive"]["diff"], "post_delivery_reviews": post["naive"]["diff"]}
    carrier = carrier_leg_design(r_post)
    iv = strike_iv(d)
    rep = repurchase_models(d)
    sizing = impact_sizing(d, recorded, post, rep)
    write_report("delivery_impact", {
        "sample": {"delivered_revenue_orders": int(len(d)), "with_review": int(len(r_all)),
                   "with_post_delivery_review": int(len(r_post)), "late_share": float(d["late"].mean()),
                   "window": f"{WINDOW_START}..{WINDOW_END}",
                   "excluded": "revenue orders never delivered (no delivery date; see DQ35)"},
        "survey_timing": timing,
        "review": recorded,
        "review_post_delivery": post,
        "bounds": bounds,
        "design_caveats": {
            "D_same_delivery_time": "Conditions on delivery time, which the promise partly causes (bunching "
            "before the promise): a mediator. Within a delivery-day cell a late order is one abnormally slow "
            "for its lane (lost parcel, re-shipment). Descriptive only.",
            "C_within_seller_month": "Removes seller quality and drift; order-level shocks (stockouts, "
            "wrong/missing items) can still drive both lateness and low scores.",
        },
        "E_carrier_leg_only": carrier,
        "F_strike_iv": iv,
        "rd_appendix": rd_appendix(r_all),
        "repurchase": rep,
        "impact": sizing,
    })
    print(bounds)
    print("carrier-leg:", round(carrier["estimate"], 3), carrier["ci95"])
    print("strike robustness", iv["recorded_robustness"], iv["post_delivery_share_strike_vs_control"])
    for k in ("recorded_all_reviews", "post_delivery_reviews"):
        v = iv[k]
        print("strike IV", k, round(v["iv_late_effect"]["estimate"], 3), v["iv_late_effect"]["ci95"],
              "F", round(v["first_stage_F"], 1), "late", round(v["late_rate_strike_window"], 3),
              round(v["late_rate_control_windows"], 3), "n", v["n"])
    print("repurchase", rep["fe_lpm"]["estimate"], rep["mde_80pct_power"], rep["mde_relative_to_base"])
    print("lever", sizing["survey_on_delivery_lever"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
