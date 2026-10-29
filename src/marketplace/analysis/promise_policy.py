"""Delivery-promise calibration (H1-H3), evaluated over a full year including the peak.

1. Padding: how much Olist's promised dates exceed actual delivery (overall/lane/category).
2. Quantile models (P50/P80/P90 of delivery days) from checkout-time features only, retrained
   every month M on purchases from months M-w-1..M-2 that were delivered before M started.
   Seller/lane history features use STRICTLY PRIOR deliveries (delivered before the order's
   own purchase timestamp), never the row's own label.
3. Policy evaluation, rolling, Oct-2017..Aug-2018 (Black Friday, holiday peak, the Feb/Mar
   2018 carrier slowdown and the May-2018 strike are all inside):
     SELECTION period Oct-2017..Mar-2018 -> choose the training window and the policy
     TEST period      Apr-2018..Aug-2018 -> report, never used for choices
   Revenue orders that were never delivered count as LATE under every policy.
4. Trade-off curve: lane-quantile promises for q in 0.50..0.99 plus a drift-aware policy that
   re-picks q each month to hit a late-rate target on the latest fully observed month.
   Each point is costed under two survey regimes (today: survey at promise+2 days; or survey
   on confirmed delivery), and given a break-even conversion elasticity.

Run: python -m marketplace.analysis.promise_policy
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from marketplace.analysis.common import WINDOW_END, df, read_report, write_report
from marketplace.analysis.delivery_impact import lateness_bin

EVAL = ("2017-10-01", WINDOW_END)
SELECT = ("2017-10-01", "2018-03-31")
TEST = ("2018-04-01", WINDOW_END)
QUANTILES = (0.5, 0.8, 0.9)
LANE_Q_GRID = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99)
WINDOW_CANDIDATES = (3, 6)
LATE_TARGET = 0.07
MIN_LANE_N = 30
NEVER = 10_000.0
FAST = bool(__import__("os").environ.get("PROMISE_FAST"))  # delivered-day number for never-delivered orders (late under any promise)

CATEGORICAL = ["seller_state", "customer_state", "category_top", "purchase_dow"]
NUMERIC = ["log_km", "km_missing", "items_price_brl", "freight_brl", "n_items", "n_sellers",
           "weight_kg", "volume_l", "purchase_hour", "olist_promised_days",
           "seller_prior_mean_days", "seller_prior_n", "lane_prior_mean_days", "lane_prior_n"]
FEATURES = CATEGORICAL + NUMERIC
FORBIDDEN = {"approved_at", "delivered_to_carrier_at", "delivered_to_customer_at", "delivery_days",
             "days_late", "is_late", "review_score", "order_status", "y"}

# Single external source for the conversion benefit, used only for a sensitivity band:
# Fisher, Gallino & Xu (2019, J. Marketing Research 56(5)): +1.45% online sales per BUSINESS day
# of faster ACTUAL delivery (a new US distribution centre, apparel). ~1.0% per calendar day.
# Transferring it from actual speed to a displayed promise on a Brazilian marketplace is an
# assumption; 0.25% / 0.5% are the analyst's haircuts, not published values.
FISHER_PER_CAL_DAY = 0.0145 / 1.4


def load() -> pd.DataFrame:
    d = df(
        f"""
        with w as (
            select i.order_id, sum(p.product_weight_g) / 1000.0 weight_kg,
                   sum(p.product_volume_cm3) / 1000.0 volume_l
            from marts.fct_order_items i join marts.dim_products p using (product_id) group by 1)
        select o.order_id, o.purchased_at, o.purchase_date, o.delivered_to_customer_at, o.is_delivered,
               o.primary_seller_id, o.primary_seller_state seller_state, o.customer_state, o.lane,
               o.primary_category category, o.n_items, o.n_sellers,
               o.items_price_brl::double items_price_brl, o.freight_brl::double freight_brl,
               o.seller_customer_km, o.promised_days olist_promised_days, o.is_first_order,
               date_diff('day', o.purchase_date, cast(o.delivered_to_customer_at as date)) delivered_day_number,
               w.weight_kg, w.volume_l
        from marts.fct_orders o left join w using (order_id)
        where o.is_revenue_order and o.purchase_date between '2017-01-01' and '{WINDOW_END}'
        """
    )
    d["km_missing"] = d["seller_customer_km"].isna().astype(int)
    d["log_km"] = np.log1p(d["seller_customer_km"].fillna(0))
    d["purchase_dow"] = d["purchased_at"].dt.dayofweek.astype(str)
    d["purchase_hour"] = d["purchased_at"].dt.hour
    d["y"] = d["delivered_day_number"].astype(float)
    d["purchase_date"] = pd.to_datetime(d["purchase_date"])
    d["pm"] = d["purchase_date"].dt.to_period("M")
    return add_prior_history(d)


def add_prior_history(d: pd.DataFrame) -> pd.DataFrame:
    """Seller and lane history from deliveries completed STRICTLY BEFORE each order's purchase
    timestamp (what the system could know at checkout). Never includes the order itself."""
    d = d.sort_values("purchased_at").reset_index(drop=True)
    ev = d[d.delivered_to_customer_at.notna()][["primary_seller_id", "lane", "delivered_to_customer_at", "y"]]
    for key, name in (("primary_seller_id", "seller"), ("lane", "lane")):
        e = ev.sort_values("delivered_to_customer_at").copy()
        e["cum_n"] = e.groupby(key).cumcount() + 1
        e["cum_y"] = e.groupby(key)["y"].cumsum()
        left = d[["purchased_at", key]].reset_index()
        m = pd.merge_asof(left.sort_values("purchased_at"), e[[key, "delivered_to_customer_at", "cum_n", "cum_y"]],
                          left_on="purchased_at", right_on="delivered_to_customer_at", by=key,
                          direction="backward", allow_exact_matches=False).set_index("index")
        d[f"{name}_prior_n"] = m["cum_n"].reindex(d.index).fillna(0)
        d[f"{name}_prior_mean_days"] = (m["cum_y"] / m["cum_n"]).reindex(d.index)
    return d


def _encode(frames, cats=None):
    top = frames[0]["category"].value_counts().head(40).index
    out = []
    for f in frames:
        f = f.copy()
        f["category_top"] = np.where(f["category"].isin(top), f["category"], "other")
        out.append(f)
    cats = cats or {c: sorted(out[0][c].astype(str).unique()) for c in CATEGORICAL}
    enc = []
    for f in out:
        x = f[FEATURES].copy()
        for c in CATEGORICAL:
            x[c] = pd.Categorical(x[c].astype(str), categories=cats[c]).codes.astype(float)
            x.loc[x[c] < 0, c] = np.nan
        enc.append(x)
    return enc


def train_rows(d: pd.DataFrame, month: pd.Period, window: int) -> pd.DataFrame:
    """Rows usable to predict month M: purchased in M-window-1..M-2 AND delivered before M."""
    start = month.to_timestamp()
    lo, hi = month - (window + 1), month - 2
    return d[(d.pm >= lo) & (d.pm <= hi) & (d.delivered_to_customer_at < start)]


def lane_quantile(tr: pd.DataFrame, te: pd.DataFrame, q: float) -> np.ndarray:
    lane = tr.groupby("lane")["y"].quantile(q)
    n = tr.groupby("lane").size()
    state = tr.groupby("customer_state")["y"].quantile(q)
    glob = float(tr["y"].quantile(q))
    return te["lane"].map(lane.where(n >= MIN_LANE_N)).fillna(te["customer_state"].map(state)).fillna(glob).to_numpy()


def rolling(d: pd.DataFrame, window: int, with_model: bool = True) -> pd.DataFrame:
    out = []
    for month in pd.period_range(EVAL[0], EVAL[1], freq="M"):
        tr = train_rows(d, month, window)
        te = d[d.pm == month].copy()
        for q in LANE_Q_GRID:
            te[f"lane_q{int(q * 100)}"] = lane_quantile(tr, te, q)
        # Drift-aware: pick the smallest lane quantile whose promise would have met the late
        # target on the latest fully observed month (M-2, deliveries known before M starts),
        # using lanes estimated on the months before it.
        obs_month = month - 2
        obs = d[(d.pm == obs_month)]
        tr_obs = train_rows(d, obs_month, window)
        chosen = LANE_Q_GRID[-1]
        if len(obs) and len(tr_obs):
            for q in LANE_Q_GRID:
                p = np.ceil(lane_quantile(tr_obs, obs, q))
                y = np.where(obs.delivered_to_customer_at < month.to_timestamp(), obs.y, NEVER)
                if np.mean(y > p) <= LATE_TARGET:
                    chosen = q
                    break
        te["recal_q"] = chosen
        te["lane_recalibrated"] = lane_quantile(tr, te, chosen)
        if with_model and not FAST:
            xtr, xte = _encode([tr, te])
            mask = [c in CATEGORICAL for c in FEATURES]
            for q in QUANTILES:
                m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=250, learning_rate=0.06,
                                                  max_leaf_nodes=31, min_samples_leaf=50,
                                                  categorical_features=mask, random_state=7)
                m.fit(xtr, tr["y"])
                te[f"model_p{int(q * 100)}"] = m.predict(xte)
        if not with_model or FAST:  # smoke mode: lane quantiles stand in for the GBM
            for q in QUANTILES:
                te[f"model_p{int(q * 100)}"] = te[f"lane_q{int(q * 100)}"]
        te["train_n"] = len(tr)
        out.append(te)
    r = pd.concat(out)
    r["y_eval"] = r["y"].fillna(NEVER)  # never delivered = late under any promise
    return r


def pinball(y, p, q) -> float:
    e = y - p
    return float(np.mean(np.maximum(q * e, (q - 1) * e)))


def coverage_report(r: pd.DataFrame) -> dict:
    out = {}
    for name, (a, b) in {"selection": SELECT, "test": TEST}.items():
        s = r[(r.purchase_date >= pd.Timestamp(a)) & (r.purchase_date <= pd.Timestamp(b))]
        dlv = s[s.is_delivered]
        row = {"n": int(len(s)), "n_never_delivered": int((~s.is_delivered).sum())}
        for q in QUANTILES:
            tag = f"p{int(q * 100)}"
            row[tag] = {
                "model_coverage_ceil": float(np.mean(s.y_eval <= np.ceil(s[f"model_{tag}"]))),
                "model_coverage_raw": float(np.mean(s.y_eval <= s[f"model_{tag}"])),
                "lane_coverage_ceil": float(np.mean(s.y_eval <= np.ceil(s[f"lane_q{int(q * 100)}"]))),
                "model_pinball_delivered": pinball(dlv.y, dlv[f"model_{tag}"], q),
                "lane_pinball_delivered": pinball(dlv.y, dlv[f"lane_q{int(q * 100)}"], q),
                "olist_pinball_delivered": pinball(dlv.y, dlv.olist_promised_days, q),
            }
        out[name] = row
    return out


def simulate(s: pd.DataFrame, promise: np.ndarray, effects: dict, brl_per_bad: float, rep: dict,
             months: int) -> dict:
    """One policy on rows s. effects: {regime: (review dose-response, low-review dose-response)}."""
    promise = np.ceil(np.asarray(promise, float)).clip(min=1)
    y = s["y_eval"].to_numpy()
    cur = s["olist_promised_days"].to_numpy().astype(float)
    late_new, late_cur = y > promise, y > cur
    dlv = s["is_delivered"].to_numpy()
    nb = lateness_bin(pd.Series(np.where(dlv, y - promise, 0), index=s.index))
    cb = lateness_bin(pd.Series(np.where(dlv, y - cur, 0), index=s.index))
    annual = 12 / months
    days_saved = float(np.mean(cur - promise))
    gmv_annual = float(s["items_price_brl"].sum()) * annual
    extra_late_first = int(((late_new & ~late_cur) & s.is_first_order.to_numpy()).sum()
                           - ((late_cur & ~late_new) & s.is_first_order.to_numpy()).sum())
    aov = float(s["items_price_brl"].mean())
    rep_loss = -rep["fe_lpm"]["estimate"] * extra_late_first * aov * annual
    out = {
        "mean_promise_days": float(promise.mean()),
        "mean_days_saved_vs_current": days_saved,
        "late_rate": float(late_new.mean()),
        "late_rate_current": float(late_cur.mean()),
        "delta_late_pp": float(100 * (late_new.mean() - late_cur.mean())),
        "extra_late_orders_per_year": float((late_new.sum() - late_cur.sum()) * annual),
        "repurchase_gmv_at_risk_brl_per_year": rep_loss,
        "gmv_per_year": gmv_annual,
    }
    for regime, (rev, low) in effects.items():
        rv = {b["bin"]: b["effect"] for b in rev}
        lw = {b["bin"]: b["effect"] for b in low}
        d_rev = np.where(dlv, nb.map(rv) - cb.map(rv), 0.0)
        d_low = np.where(dlv, nb.map(lw) - cb.map(lw), 0.0)
        extra_bad = float(np.nansum(d_low) * annual)
        cost = rep_loss + max(0.0, -brl_per_bad) * extra_bad
        out[regime] = {
            "expected_delta_avg_review": float(np.nanmean(d_rev)),
            "extra_1_2_star_reviews_per_year": extra_bad,
            "cost_brl_per_year": cost,
            "breakeven_conversion_lift_per_promise_day": (max(cost, 0.0) / (gmv_annual * days_saved)) if days_saved > 0 else None,
        }
    out["upside_brl_per_year_at_fisher_bound"] = gmv_annual * FISHER_PER_CAL_DAY * max(days_saved, 0)
    return out


def padding_report(d: pd.DataFrame) -> dict:
    d = d[d.is_delivered & (d.purchase_date >= pd.Timestamp("2017-01-01"))].copy()
    d["padding"] = d["olist_promised_days"] - d["y"]

    def grp(col, min_n):
        g = d.groupby(col).agg(n=("padding", "size"), median_padding=("padding", "median"),
                               p10_padding=("padding", lambda s: np.quantile(s, 0.1)),
                               median_promised=("olist_promised_days", "median"), median_actual=("y", "median"),
                               late_rate=("padding", lambda s: float((s < 0).mean())))
        return g[g.n >= min_n].sort_values("median_padding", ascending=False).reset_index()

    lanes, cats = grp("lane", 200), grp("category", 300)
    return {
        "definition": "padding = promised days - actual delivered day number (positive = early)",
        "n_orders": int(len(d)),
        "overall_quantiles": {f"p{int(q * 100)}": float(np.quantile(d["padding"], q)) for q in (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)},
        "share_padded_over_7_days": float((d["padding"] > 7).mean()),
        "median_promised_days": float(d["olist_promised_days"].median()),
        "median_actual_days": float(d["y"].median()),
        "lanes_most_padded": lanes.head(10), "lanes_least_padded": lanes.tail(10),
        "categories_most_padded": cats.head(8), "categories_least_padded": cats.tail(8),
        "padding_histogram": d["padding"].clip(-20, 45).round().value_counts().sort_index(),
    }


def main() -> int:
    d = load()
    assert not set(FEATURES) & FORBIDDEN
    di = read_report("delivery_impact")
    rv = read_report("review_value")["brl_next4w_gmv_per_extra_bad_review"]
    effects = {
        "survey_today": (di["review"]["G_dose_response"]["fe_plus_delivery_days"],
                         di["review"]["G_dose_response"]["low_review_fe_plus_delivery_days"]),
        "survey_on_delivery": (di["review_post_delivery"]["G_dose_response"]["fe_plus_delivery_days"],
                               di["review_post_delivery"]["G_dose_response"]["low_review_fe_plus_delivery_days"]),
    }
    rep = di["repurchase"]
    brl_per_bad = rv["estimate"]

    # choose GBM window on the SELECTION period only
    runs = {w: rolling(d, w) for w in (WINDOW_CANDIDATES[:1] if FAST else WINDOW_CANDIDATES)}
    sel_mask = lambda r: (r.purchase_date >= pd.Timestamp(SELECT[0])) & (r.purchase_date <= pd.Timestamp(SELECT[1]))  # noqa: E731
    win_score = {w: float(np.mean([pinball(r[sel_mask(r) & r.is_delivered].y, r[sel_mask(r) & r.is_delivered][f"model_p{int(q*100)}"], q)
                                   for q in QUANTILES])) for w, r in runs.items()}
    window = min(win_score, key=win_score.get)
    r = runs[window]
    periods = {"selection": SELECT, "test": TEST, "full_year": EVAL}
    policies = {"current_olist_estimate": "olist_promised_days", "uniform_minus_5_days": None,
                **{f"lane_q{int(q * 100)}": f"lane_q{int(q * 100)}" for q in LANE_Q_GRID},
                "lane_recalibrated_to_7pct_late": "lane_recalibrated",
                "lane_q80_capped_5d": "CAPPED",
                "model_p80": "model_p80", "model_p90": "model_p90"}
    sims = {}
    for pname, (a, b) in periods.items():
        s = r[(r.purchase_date >= pd.Timestamp(a)) & (r.purchase_date <= pd.Timestamp(b))]
        months = s.pm.nunique()
        sims[pname] = {}
        for k, col in policies.items():
            if col is None:
                prom = s["olist_promised_days"].to_numpy() - 5
            elif col == "CAPPED":  # the A/B variant: never more than 5 days shorter than today
                prom = np.maximum(np.ceil(s["lane_q80"].to_numpy()), s["olist_promised_days"].to_numpy() - 5)
            else:
                prom = s[col].to_numpy()
            sims[pname][k] = simulate(s, prom, effects, brl_per_bad, rep, months)
    # Recommendation rule (fixed before results): on the SELECTION period, the shortest mean
    # promise with late rate <= 7% (never-delivered counted late) and expected recorded review
    # change >= -0.05. If none qualifies, recommend keeping the current promise.
    sel = sims["selection"]
    ok = {k: v for k, v in sel.items() if k != "current_olist_estimate" and v["late_rate"] <= LATE_TARGET
          and v["survey_today"]["expected_delta_avg_review"] >= -0.05}
    rec = min(ok, key=lambda k: ok[k]["mean_promise_days"]) if ok else "current_olist_estimate"
    by_month = (r.groupby(r.pm.astype(str)).apply(lambda g: pd.Series({
        "n": len(g), "current_late": float(np.mean(g.y_eval > g.olist_promised_days)),
        "lane_q80_late": float(np.mean(g.y_eval > np.ceil(g.lane_q80))),
        "recalibrated_late": float(np.mean(g.y_eval > np.ceil(g.lane_recalibrated))),
        "recal_q": float(g.recal_q.iloc[0]),
        "model_p90_coverage": float(np.mean(g.y_eval <= np.ceil(g.model_p90))),
        "median_actual": float(g.y.median()), "mean_olist_promise": float(g.olist_promised_days.mean())}),
        include_groups=False).reset_index().rename(columns={"pm": "month"}))
    lanes_tbl = (r[r.purchase_date >= pd.Timestamp(TEST[0])]
                 .assign(late_cur=lambda x: x.y_eval > x.olist_promised_days)
                 .groupby("lane").agg(n=("y_eval", "size"), current=("olist_promised_days", "mean"),
                                      lane_p80=("lane_q80", lambda s: float(np.ceil(s).mean())),
                                      actual_median=("y", "median"), late_current=("late_cur", "mean"))
                 .query("n >= 100").reset_index())
    write_report("promise_policy", {
        "padding": padding_report(d),
        "design": {"selection_period": SELECT, "test_period": TEST, "chosen_window_months": window,
                   "window_selection_mean_pinball": win_score, "features": FEATURES,
                   "forbidden_post_purchase_fields": sorted(FORBIDDEN),
                   "history_features": "strictly prior deliveries (merge_asof, delivered < purchase)",
                   "never_delivered": "counted as late under every policy",
                   "coverage_note": "ceil() of the predicted quantile is the integer promise; coverage reported "
                   "both raw and ceil."},
        "coverage": coverage_report(r),
        "policies": sims,
        "recommendation_rule": "on the SELECTION period (Oct-2017..Mar-2018): shortest mean promise with late "
        "rate <= 7% (never-delivered = late) and recorded review change >= -0.05; else keep current",
        "recommended_policy": rec,
        "by_month": by_month,
        "review_cost_basis": {"brl_per_bad_review_next4w": rv, "survey_today": "all-review dose-response "
                              "(holding delivery time)", "survey_on_delivery": "post-delivery-review dose-response"},
        "conversion_source": "Fisher, Gallino & Xu (2019) J. Marketing Research 56(5): +1.45% sales per business "
        "day of faster ACTUAL delivery (US apparel, new DC). Not a promise-display experiment; transfer is an "
        "assumption. Break-even elasticities are reported instead of a benefit.",
        "test_lanes_for_dashboard": lanes_tbl,
    })
    for pname in periods:
        print(pname)
        for k, v in sims[pname].items():
            print(f"  {k:<32} promise {v['mean_promise_days']:5.1f} saved {v['mean_days_saved_vs_current']:5.1f} "
                  f"late {v['late_rate']:.3f} rev_today {v['survey_today']['expected_delta_avg_review']:+.3f} "
                  f"rev_ondelivery {v['survey_on_delivery']['expected_delta_avg_review']:+.3f} "
                  f"BE {v['survey_today']['breakeven_conversion_lift_per_promise_day']}")
    print("window", window, "recommended", rec)
    print(by_month.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
