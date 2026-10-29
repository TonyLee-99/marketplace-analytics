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
    out = {
        "gmv_from": g0["gmv"],
        "gmv_to": g1["gmv"],
        "delta_gmv": total,
        "pct_change": g1["gmv"] / g0["gmv"] - 1,
    }
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
    seg["growth_pct"] = np.where(
        seg["g0"] > 0, seg["g1"] / seg["g0"].replace(0, np.nan) - 1, np.nan
    )
    return seg.sort_values("delta", ascending=False).head(top).to_dict(orient="records")


def supply_side(ml: MetricsLayer) -> dict:
    """Seller-side view: GMV = active sellers x GMV per active seller; new vs existing sellers;
    the MQL -> won -> first-sale funnel; and the plateau since Nov-2017."""
    m = df(
        """
        with first_sale as (select seller_id, min(purchase_month) first_m from marts.fct_order_items
                            where is_revenue_order group by 1)
        select i.purchase_month m, count(distinct i.seller_id) active_sellers, sum(i.price_brl)::double gmv,
               sum(i.price_brl) filter (where f.first_m = i.purchase_month)::double gmv_new_sellers,
               count(distinct i.seller_id) filter (where f.first_m = i.purchase_month) new_sellers
        from marts.fct_order_items i join first_sale f using (seller_id)
        where i.is_revenue_order and i.purchase_month between '2017-01-01' and '2018-08-01'
        group by 1 order by 1
        """
    )
    m["gmv_per_seller"] = m["gmv"] / m["active_sellers"]
    m["m"] = pd.to_datetime(m["m"]).dt.strftime("%Y-%m")
    g = m.set_index("m")

    def lmdi(a, b):
        A = g.loc[a].sum() if isinstance(a, list) else g.loc[a]
        B = g.loc[b].sum() if isinstance(b, list) else g.loc[b]
        na, nb = (len(a) if isinstance(a, list) else 1), (len(b) if isinstance(b, list) else 1)
        ga, gb = A["gmv"] / na, B["gmv"] / nb
        sa, sb = A["active_sellers"] / na, B["active_sellers"] / nb
        ln = np.log(gb / ga)
        parts = {"active_sellers": np.log(sb / sa), "gmv_per_seller": np.log((gb / sb) / (ga / sa))}
        return {"gmv_from": ga, "gmv_to": gb, "pct_change": gb / ga - 1,
                "drivers": {k: {"log_change": v, "contribution_brl": (gb - ga) * v / ln} for k, v in parts.items()},
                "sellers_from": sa, "sellers_to": sb, "gmv_per_seller_from": ga / sa, "gmv_per_seller_to": gb / sb}

    mam, jja = ["2018-03", "2018-04", "2018-05"], ["2018-06", "2018-07", "2018-08"]
    jj = ["2018-06", "2018-07"]  # full months only: daily capture decays from Aug 21 (extract artefact)
    d20 = df(
        """
        select strftime(purchase_date, '%Y-%m') m, sum(items_price_brl)::double gmv
        from marts.fct_orders where is_revenue_order and day(purchase_date) <= 20
          and purchase_date between '2018-03-01' and '2018-08-20' group by 1
        """
    ).set_index("m")["gmv"]
    tail = df(
        """
        select purchase_date d, count(*) n from marts.fct_orders
        where is_revenue_order and purchase_date between '2018-08-14' and '2018-08-31' group by 1 order by 1
        """
    )
    funnel = df(
        """
        select count(*) mqls, count(*) filter (where is_won) won, count(*) filter (where has_sold) sold,
               sum(seller_gmv_brl) filter (where has_sold)::double gmv_from_funnel_sellers
        from marts.fct_seller_funnel
        """
    ).iloc[0].to_dict()
    gmv_2018 = ml.value("gmv", start="2018-01-01", end="2018-08-31")
    return {
        "monthly": m,
        "plateau": {
            "avg_monthly_gmv_nov17_feb18": float(g.loc["2017-11":"2018-02", "gmv"].mean()),
            "avg_monthly_gmv_mar_may_2018": float(g.loc[mam, "gmv"].mean()),
            "avg_monthly_gmv_jun_aug_2018": float(g.loc[jja, "gmv"].mean()),
            "jun_aug_vs_mar_may_incl_truncated_august": float(g.loc[jja, "gmv"].mean() / g.loc[mam, "gmv"].mean() - 1),
            "jun_jul_vs_mar_may_full_months": float(g.loc[jj, "gmv"].mean() / g.loc[mam, "gmv"].mean() - 1),
            "days_1_20_jun_aug_vs_mar_may": float(d20.loc[jja].mean() / d20.loc[mam].mean() - 1),
            "aug_1_20_vs_may_1_20": float(d20.loc["2018-08"] / d20.loc["2018-05"] - 1),
            "aug_daily_orders_14_31": tail.assign(d=lambda x: x.d.astype(str)).to_dict(orient="records"),
            "caveats": "Daily capture decays from 2018-08-21 (extract artefact), so August is excluded or "
            "day-matched. The FIFA World Cup (14 Jun - 15 Jul 2018, Brazil playing) overlaps the weak Jun-Jul "
            "window; not tested.",
        },
        "jun_jul_vs_mar_may_seller_tree": lmdi(mam, jj),
        "new_seller_gmv_share_2018": float(g.loc["2018-01":"2018-08", "gmv_new_sellers"].sum()
                                           / g.loc["2018-01":"2018-08", "gmv"].sum()),
        "funnel": {**{k: float(v) for k, v in funnel.items()},
                   "win_rate": float(funnel["won"] / funnel["mqls"]),
                   "sold_rate_of_won": float(funnel["sold"] / funnel["won"]),
                   "funnel_seller_share_of_2018_gmv": float(funnel["gmv_from_funnel_sellers"] / gmv_2018)},
        "sample_note": "Olist describes the public file as '100k orders from 2016 to 2018'; it does not say "
        "whether it is complete. Internal signs of an extract: Nov-2016 has no orders and capture stops on "
        "2018-08-29. Read levels as sample-level and month-to-month trends with caution.",
    }


def main() -> int:
    ml = MetricsLayer.load()
    m = tree(
        ml.compute(
            ["gmv", "orders", "active_customers", "aov"],
            grain="month",
            start="2017-01-01",
            end="2018-08-31",
        )
    )
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
            "supply_side": supply_side(ml),
        },
    )
    d = ytd["drivers"]
    print(
        f"YTD GMV {ytd['gmv_from']:,.0f} -> {ytd['gmv_to']:,.0f} ({ytd['pct_change']:+.1%}); "
        + ", ".join(
            f"{k} {v['pct_change']:+.1%} = {v['contribution_brl']:,.0f} BRL" for k, v in d.items()
        )
        + f"; residual {ytd['log_residual']:.2e}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
