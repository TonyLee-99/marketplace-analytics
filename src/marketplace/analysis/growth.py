"""(a) GMV metric tree: GMV = active customers x orders per customer x AOV.

Uses the governed metrics (gmv, orders, active_customers) from the metrics layer, then a
log (LMDI) decomposition so the three drivers add up to the total change EXACTLY:

    ln(G1/G0) = ln(C1/C0) + ln(F1/F0) + ln(A1/A0)
    contribution_i (BRL) = (G1 - G0) * ln-ratio_i / ln(G1/G0)

Also: which categories / customer states contributed most of the YoY growth.
Run: python -m marketplace.analysis.growth
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from marketplace.analysis.common import df, write_report
from marketplace.metrics import MetricsLayer

DRIVERS = ("active_customers", "orders_per_customer", "aov")


def tree(monthly: pd.DataFrame) -> pd.DataFrame:
    t = monthly[["gmv", "orders", "active_customers", "aov"]].copy()
    t["orders_per_customer"] = t["orders"] / t["active_customers"]
    return t


def decompose(g0: pd.Series, g1: pd.Series) -> dict:
    """LMDI decomposition of the change between two metric-tree rows."""
    total = g1["gmv"] - g0["gmv"]
    ln_total = np.log(g1["gmv"] / g0["gmv"])
    out = {"gmv_from": g0["gmv"], "gmv_to": g1["gmv"], "delta_gmv": total,
           "pct_change": g1["gmv"] / g0["gmv"] - 1}
    parts = {}
    for d in DRIVERS:
        ln_i = np.log(g1[d] / g0[d])
        parts[d] = {
            "from": g0[d],
            "to": g1[d],
            "pct_change": g1[d] / g0[d] - 1,
            "log_change": ln_i,
            "contribution_brl": total * ln_i / ln_total if ln_total != 0 else 0.0,
        }
    out["drivers"] = parts
    out["log_residual"] = ln_total - sum(p["log_change"] for p in parts.values())
    out["main_driver"] = max(parts, key=lambda k: abs(parts[k]["contribution_brl"]))
    return out


def segment_contribution(dim: str, a: tuple, b: tuple, top: int = 8) -> list[dict]:
    """Each segment's share of the total GMV change between two windows (additive)."""
    col = {"category": "category", "customer_state": "customer_state"}[dim]
    seg = df(
        f"""
        select {col} as segment,
               sum(price_brl) filter (where purchase_date between '{a[0]}' and '{a[1]}') as g0,
               sum(price_brl) filter (where purchase_date between '{b[0]}' and '{b[1]}') as g1
        from marts.fct_order_items where is_revenue_order group by 1
        """
    ).fillna(0)
    seg["delta"] = seg["g1"] - seg["g0"]
    tot = seg["delta"].sum()
    seg["share_of_growth"] = seg["delta"] / tot
    seg["share_of_gmv_from"] = seg["g0"] / seg["g0"].sum()
    seg["share_of_gmv_to"] = seg["g1"] / seg["g1"].sum()
    seg["growth_pct"] = np.where(seg["g0"] > 0, seg["g1"] / seg["g0"].replace(0, np.nan) - 1,
                                 np.nan)
    return seg.sort_values("delta", ascending=False).head(top).to_dict(orient="records")


def main() -> int:
    ml = MetricsLayer.load()
    m = tree(ml.compute(["gmv", "orders", "active_customers", "aov"], grain="month",
                        start="2017-01-01", end="2018-08-31"))
    m.index = pd.to_datetime(m.index)
    mom = []
    for i in range(1, len(m)):
        r = decompose(m.iloc[i - 1], m.iloc[i])
        r["month"] = m.index[i].strftime("%Y-%m")
        mom.append(r)
    yoy = []
    for ts in m.index:
        prev = ts - pd.DateOffset(years=1)
        if prev in m.index:
            r = decompose(m.loc[prev], m.loc[ts])
            r["month"] = ts.strftime("%Y-%m")
            yoy.append(r)
    # Year-to-date Jan-Aug 2018 vs Jan-Aug 2017 (same metric layer, 'all' grain on windows).
    w17, w18 = ("2017-01-01", "2017-08-31"), ("2018-01-01", "2018-08-31")
    names = ["gmv", "orders", "active_customers", "aov"]
    g0 = tree(ml.compute(names, grain="all", start=w17[0], end=w17[1])).iloc[0]
    g1 = tree(ml.compute(names, grain="all", start=w18[0], end=w18[1])).iloc[0]
    ytd = decompose(g0, g1)
    write_report(
        "growth",
        {
            "identity": "GMV = active_customers x orders_per_customer x AOV",
            "monthly_tree": m.reset_index().assign(period=lambda x: x.period.dt.strftime("%Y-%m")),
            "mom": mom,
            "yoy": yoy,
            "ytd_jan_aug_2018_vs_2017": ytd,
            "ytd_category_contribution": segment_contribution("category", w17, w18),
            "ytd_state_contribution": segment_contribution("customer_state", w17, w18),
        },
    )
    d = ytd["drivers"]
    print(
        f"YTD GMV {ytd['gmv_from']:,.0f} -> {ytd['gmv_to']:,.0f} ({ytd['pct_change']:+.1%}); "
        + ", ".join(f"{k} {v['pct_change']:+.1%} = {v['contribution_brl']:,.0f} BRL"
                    for k, v in d.items())
        + f"; residual {ytd['log_residual']:.2e}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
