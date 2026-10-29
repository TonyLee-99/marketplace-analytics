"""(b) Cohort retention and repeat-purchase curves (person = customer_unique_id).

* Monthly acquisition cohorts (month of first revenue order), retention = share of the
  cohort with a revenue order k months later (k = 1..12), only where fully observed.
* Time to 2nd order: Kaplan-Meier curve (handles right-censoring at the data end), with and
  without same-day "repeat" orders (split baskets placed minutes apart are not loyalty).
* Share of GMV from repeat orders, and what that implies for the business model.

Run: python -m marketplace.analysis.cohorts
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from marketplace.analysis.common import WINDOW_END, df, write_report
from marketplace.metrics import MetricsLayer

DATA_END = pd.Timestamp(WINDOW_END)


def kaplan_meier(durations: np.ndarray, observed: np.ndarray, at_days: list[int]) -> dict:
    """Cumulative incidence 1 - S(t) of a 2nd order, KM estimator."""
    order = np.argsort(durations)
    t, e = durations[order], observed[order]
    times = np.unique(t[e == 1])
    s, surv = 1.0, {}
    n_at_risk = len(t)
    idx = 0
    curve = []
    for ti in times:
        while idx < len(t) and t[idx] < ti:
            n_at_risk -= 1
            idx += 1
        d = int(((t == ti) & (e == 1)).sum())
        s *= 1 - d / n_at_risk
        curve.append((float(ti), s))
    for day in at_days:
        vals = [sv for ti, sv in curve if ti <= day]
        surv[day] = 1 - (vals[-1] if vals else 1.0)
    return surv


def main() -> int:
    orders = df(
        f"""
        select customer_unique_id, order_id, purchased_at, purchase_month, items_price_brl,
               customer_order_number
        from marts.fct_orders
        where is_revenue_order and purchase_date <= '{WINDOW_END}'
        """
    )
    orders["purchase_month"] = pd.to_datetime(orders["purchase_month"])
    first = orders[orders.customer_order_number == 1].set_index("customer_unique_id")
    orders["cohort"] = orders["customer_unique_id"].map(first["purchase_month"])
    orders["k"] = (
        (orders["purchase_month"].dt.year - orders["cohort"].dt.year) * 12
        + orders["purchase_month"].dt.month - orders["cohort"].dt.month
    )
    sizes = first.groupby("purchase_month").size()
    active = orders.groupby(["cohort", "k"])["customer_unique_id"].nunique().unstack(fill_value=0)
    last_month = pd.Timestamp(WINDOW_END).to_period("M").to_timestamp()
    retention = {}
    for cohort in active.index:
        if cohort < pd.Timestamp("2017-01-01"):
            continue
        row = {}
        for k in range(1, 13):
            if cohort + pd.DateOffset(months=k) > last_month:
                break
            row[k] = active.loc[cohort].get(k, 0) / sizes[cohort]
        retention[cohort.strftime("%Y-%m")] = {"size": int(sizes[cohort]), "retention": row}
    # Average retention curve weighted by cohort size over fully observed cohorts.
    avg_curve = {}
    for k in range(1, 13):
        num = sum(v["retention"][k] * v["size"] for v in retention.values() if k in v["retention"])
        den = sum(v["size"] for v in retention.values() if k in v["retention"])
        avg_curve[k] = num / den if den else None

    # Time to second order (KM), with/without same-day repeats.
    o = orders.sort_values(["customer_unique_id", "purchased_at"])
    o["next_at"] = o.groupby("customer_unique_id")["purchased_at"].shift(-1)
    f = o[o.customer_order_number == 1].copy()
    f = f[f.purchased_at >= "2017-01-01"]
    at_days = [7, 30, 90, 180, 365]
    gap = (f["next_at"] - f["purchased_at"]).dt.total_seconds() / 86400
    censor = (DATA_END - f["purchased_at"]).dt.total_seconds() / 86400
    obs_all = gap.notna().to_numpy()
    km_all = kaplan_meier(np.where(obs_all, gap, censor), obs_all.astype(int), at_days)
    # Exclude same calendar-day next orders: look for the next order on a later day.
    o["pdate"] = o["purchased_at"].dt.normalize()
    later = o.merge(o[["customer_unique_id", "purchased_at", "pdate"]], on="customer_unique_id",
                    suffixes=("", "_n"))
    later = later[later.pdate_n > later.pdate]
    nxt = later.groupby("order_id")["purchased_at_n"].min()
    gap2 = (f["order_id"].map(nxt) - f["purchased_at"]).dt.total_seconds() / 86400
    obs2 = gap2.notna().to_numpy()
    km_later = kaplan_meier(np.where(obs2, gap2, censor), obs2.astype(int), at_days)
    same_day_share = float(((gap < 1) & (f["next_at"].dt.normalize() == f["purchased_at"].dt.normalize())).sum()
                           / max(obs_all.sum(), 1))

    ml = MetricsLayer.load()
    repeat_gmv = float(orders.loc[orders.customer_order_number >= 2, "items_price_brl"].sum())
    total_gmv = ml.value("gmv", end=WINDOW_END)
    people = orders["customer_unique_id"].nunique()
    n_orders_dist = orders.groupby("customer_unique_id").size().value_counts().sort_index()
    med_gap = float(gap2[obs2].median())
    write_report(
        "cohorts",
        {
            "people": people,
            "people_with_2plus_orders": int((orders.groupby("customer_unique_id").size() >= 2).sum()),
            "lifetime_repeat_rate": float((orders.groupby("customer_unique_id").size() >= 2).mean()),
            "orders_per_person_distribution": n_orders_dist.head(6),
            "repeat_gmv_share": repeat_gmv / total_gmv,
            "km_cumulative_2nd_order_any": km_all,
            "km_cumulative_2nd_order_later_day": km_later,
            "share_of_next_orders_same_day": same_day_share,
            "median_days_to_2nd_order_later_day": med_gap,
            "avg_retention_curve": avg_curve,
            "cohort_retention": retention,
            "implication": f"Olist is an acquisition-driven marketplace: "
            f"{1 - float((orders.groupby('customer_unique_id').size() >= 2).mean()):.1%} of "
            "buyers order once. Customer LTV is roughly the first order's margin, so CAC must pay back on "
            "the first order, and the growth model is new-customer acquisition + seller "
            "assortment, not loyalty.",
        },
    )
    print(
        f"repeat rate {float((orders.groupby('customer_unique_id').size() >= 2).mean()):.4f}; "
        f"KM 2nd order by 180d any {km_all[180]:.4f}, later-day {km_later[180]:.4f}; "
        f"same-day share {same_day_share:.3f}; repeat GMV share {repeat_gmv / total_gmv:.4f}; "
        f"month-1 retention {avg_curve[1]:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
