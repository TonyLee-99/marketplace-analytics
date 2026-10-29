"""(d) Seller scorecard, tiering and Pareto + (e) lane SLA analysis.

Seller scorecard (last 12 reliable months, 2017-09..2018-08), per seller:
  GMV, orders, on-time rate, seller-caused late rate (handed to carrier after the shipping
  limit), avg review, 1-2 star share, cancellation share, freight/price, handling days.
Tiers combine scale (GMV rank) and quality (on-time + review), so account managers know
whom to grow, whom to fix and whom to leave alone.

Lane analysis: seller_state -> customer_state lanes with >= 100 delivered orders; worst SLA
misses; opportunity = late orders avoided if a lane hit the network on-time rate, valued in
1-2 star reviews avoided (measured effect) and GMV exposed.

Run: python -m marketplace.analysis.sellers
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from marketplace.analysis.common import WINDOW_END, df, read_report, write_report
from marketplace.metrics import MetricsLayer
from marketplace.paths import REPORTS

START = "2017-09-01"
MIN_ORDERS_SCORECARD = 20
MIN_LANE_ORDERS = 100


def scorecard() -> pd.DataFrame:
    s = df(
        f"""
        with o as (
            select primary_seller_id as seller_id, order_id, order_status, is_revenue_order,
                   is_delivered, is_late, review_score, items_price_brl, freight_brl,
                   handling_days, delivered_to_carrier_at, shipping_limit_at
            from marts.fct_orders o
            where purchase_date between '{START}' and '{WINDOW_END}'
        )
        select seller_id,
               count(*) filter (where is_revenue_order)                       as orders,
               sum(items_price_brl) filter (where is_revenue_order)           as gmv_brl,
               avg(case when not is_late then 1.0 else 0 end) filter (where is_delivered)
                                                                               as on_time_rate,
               avg(case when delivered_to_carrier_at > shipping_limit_at then 1.0 else 0 end)
                   filter (where delivered_to_carrier_at is not null)          as missed_handover_rate,
               avg(review_score) filter (where is_revenue_order)               as avg_review,
               avg(case when review_score <= 2 then 1.0 else 0 end)
                   filter (where review_score is not null)                     as low_review_share,
               avg(case when order_status in ('canceled','unavailable') then 1.0 else 0 end)
                                                                               as cancel_share,
               sum(freight_brl) filter (where is_revenue_order)
                   / nullif(sum(items_price_brl) filter (where is_revenue_order), 0)
                                                                               as freight_ratio,
               median(handling_days) filter (where is_delivered)               as median_handling_days
        from o group by 1
        """
    )
    sellers = df(
        "select seller_id, seller_state, seller_region, is_from_marketing_funnel, "
        "funnel_lead_origin from marts.dim_sellers"
    )
    return s.merge(sellers, on="seller_id", how="left")


def tier(s: pd.DataFrame) -> pd.DataFrame:
    s = s.copy()
    eligible = s["orders"] >= MIN_ORDERS_SCORECARD
    s["gmv_rank_pct"] = s["gmv_brl"].rank(pct=True, ascending=True)
    net_on_time = float(
        np.average(s.loc[eligible, "on_time_rate"].fillna(0), weights=s.loc[eligible, "orders"])
    )
    net_review = float(
        np.average(s.loc[eligible, "avg_review"].fillna(0), weights=s.loc[eligible, "orders"])
    )
    good = (s["on_time_rate"] >= net_on_time - 0.03) & (s["avg_review"] >= net_review - 0.2)
    big = s["gmv_rank_pct"] >= 0.9
    s["tier"] = np.select(
        [~eligible, big & good, big & ~good, ~big & good, ~big & ~good],
        [
            "T5 long tail (<20 orders)",
            "T1 champions (top-10% GMV, quality OK)",
            "T2 fix-first (top-10% GMV, quality below bar)",
            "T3 grow (quality OK)",
            "T4 watch (quality below bar)",
        ],
        default="?",
    )
    s.attrs["bar"] = {
        "network_on_time": net_on_time,
        "network_review": net_review,
        "on_time_bar": net_on_time - 0.03,
        "review_bar": net_review - 0.2,
    }
    return s


def pareto(s: pd.DataFrame) -> dict:
    g = s.loc[s.gmv_brl > 0, "gmv_brl"].sort_values(ascending=False).to_numpy()
    cum = np.cumsum(g) / g.sum()
    n = len(g)
    pts = {
        f"top_{p}pct_sellers_share": float(cum[int(np.ceil(p / 100 * n)) - 1])
        for p in (1, 5, 10, 20, 50)
    }
    pts["sellers_for_80pct_gmv"] = int(np.searchsorted(cum, 0.8) + 1)
    pts["share_of_sellers_for_80pct_gmv"] = pts["sellers_for_80pct_gmv"] / n
    pts["active_sellers"] = n
    curve = [
        {"seller_pct": (i + 1) / n, "gmv_cum_share": float(cum[i])}
        for i in np.unique(np.linspace(0, n - 1, 101).astype(int))
    ]
    return {**pts, "curve": curve}


def lanes() -> pd.DataFrame:
    rep = read_report("delivery_impact")
    lanes = df(
        f"""
        with o as (
            select o.*
            from marts.fct_orders o
            where is_revenue_order and is_delivered
              and purchase_date between '{START}' and '{WINDOW_END}')
        select lane, primary_seller_state as seller_state, customer_state,
               count(*) as delivered_orders,
               avg(case when is_late then 1.0 else 0 end) as late_rate,
               avg(days_late) filter (where is_late) as avg_days_late_when_late,
               median(delivery_days) as median_delivery_days,
               median(promised_days) as median_promised_days,
               avg(case when is_late and delivered_to_carrier_at > shipping_limit_at
                        then 1.0 else 0 end) / nullif(avg(case when is_late then 1.0 else 0 end), 0)
                   as late_share_seller_handover_missed,
               median(carrier_transit_days) as median_transit_days,
               avg(seller_customer_km) as avg_km,
               avg(review_score) as avg_review,
               sum(items_price_brl) as gmv_brl
        from o group by 1, 2, 3
        having count(*) >= {MIN_LANE_ORDERS}
        """
    )
    net = df(
        f"select avg(case when is_late then 1.0 else 0 end) r from marts.fct_orders "
        f"where is_revenue_order and is_delivered and purchase_date between '{START}' and "
        f"'{WINDOW_END}'"
    )["r"].iloc[0]
    # Lane-adjusted baseline: expected late rate of each order from distance, destination
    # state, origin region and purchase month (no lane identity), i.e. what a lane "should"
    # run at given where it goes and how far. Excess = actual - expected, floored at 0.
    o = df(
        f"""
        select lane, is_late::int late, coalesce(seller_customer_km, 0) km,
               seller_customer_km is null km_missing, customer_state, primary_seller_region,
               cast(purchase_month as varchar) m
        from marts.fct_orders where is_revenue_order and is_delivered
          and purchase_date between '{START}' and '{WINDOW_END}'
        """
    )
    X = pd.get_dummies(o[["customer_state", "primary_seller_region", "m"]].astype(str), drop_first=True)
    X["log_km"] = np.log1p(o["km"])
    X["log_km2"] = X["log_km"] ** 2
    X["km_missing"] = o["km_missing"].astype(float)
    X.insert(0, "const", 1.0)
    beta, *_ = np.linalg.lstsq(X.to_numpy(float), o["late"].to_numpy(float), rcond=None)
    o["expected"] = X.to_numpy(float) @ beta
    exp_lane = o.groupby("lane")["expected"].mean()
    lanes["network_late_rate"] = net
    lanes["expected_late_rate_lane_adjusted"] = lanes["lane"].map(exp_lane)
    lanes["excess_late_orders_vs_network"] = (lanes["late_rate"] - net).clip(lower=0) * lanes["delivered_orders"]
    lanes["excess_late_orders"] = (
        (lanes["late_rate"] - lanes["expected_late_rate_lane_adjusted"]).clip(lower=0) * lanes["delivered_orders"])
    # Value saves at the MARGIN: a fixed lane mostly turns 1-3-day-late orders into on-time ones,
    # so use the 1-3-days-late dose-response, recorded (today's survey) and post-delivery.
    def bin_eff(block):
        return next(b["effect"] for b in block if b["bin"] == "1-3 late")
    low_rec = bin_eff(rep["review"]["G_dose_response"]["low_review_fe"])
    low_post = bin_eff(rep["review_post_delivery"]["G_dose_response"]["low_review_fe"])
    lanes["low_reviews_avoidable"] = lanes["excess_late_orders"] * low_rec
    lanes["low_reviews_avoidable_post_delivery"] = lanes["excess_late_orders"] * low_post
    lanes["gmv_on_excess_late_orders_brl"] = (
        lanes["excess_late_orders"] * lanes["gmv_brl"] / lanes["delivered_orders"]
    )
    return lanes.sort_values("excess_late_orders", ascending=False)


def main() -> int:
    ml = MetricsLayer.load()
    s = tier(scorecard())
    tiers = (
        s.groupby("tier")
        .agg(
            sellers=("seller_id", "size"),
            gmv_brl=("gmv_brl", "sum"),
            orders=("orders", "sum"),
            on_time=("on_time_rate", "mean"),
            review=("avg_review", "mean"),
        )
        .assign(gmv_share=lambda x: x.gmv_brl / x.gmv_brl.sum())
        .reset_index()
    )
    fix_first = s[s.tier.str.startswith("T2")].sort_values("gmv_brl", ascending=False)
    funnel = df(
        """
        select origin, count(*) mqls, avg(is_won::int) win_rate,
               avg(has_sold::int) filter (where is_won) sold_rate_of_won,
               sum(seller_gmv_brl) gmv_brl
        from marts.fct_seller_funnel group by 1 order by mqls desc
        """
    )
    ln = lanes()
    lanes_total = {
        "lanes_analysed": int(len(ln)),
        "orders_in_lanes": int(ln.delivered_orders.sum()),
        "excess_late_orders_total": float(ln.excess_late_orders.sum()),
        "top10_excess_late_orders": float(ln.head(10).excess_late_orders.sum()),
        "low_reviews_avoidable_total": float(ln.low_reviews_avoidable.sum()),
        "low_reviews_avoidable_top10": float(ln.head(10).low_reviews_avoidable.sum()),
        "low_reviews_avoidable_top10_post_delivery": float(ln.head(10).low_reviews_avoidable_post_delivery.sum()),
        "excess_vs_network_top10_old_method": float(ln.sort_values("excess_late_orders_vs_network", ascending=False)
                                                    .head(10).excess_late_orders_vs_network.sum()),
        "attribution_note": "late_share_seller_handover_missed = share of a lane's late orders where the seller "
        "handed over after the shipping limit; the remainder mixes carrier transit AND promise-setting error. "
        "Olist data has no carrier identifier, so no carrier-level counterfactual is possible.",
        "gmv_on_excess_late_orders_top10_brl": float(
            ln.head(10).gmv_on_excess_late_orders_brl.sum()
        ),
    }
    write_report(
        "sellers",
        {
            "window": f"{START}..{WINDOW_END}",
            "quality_bar": s.attrs["bar"],
            "tiers": tiers,
            "pareto": pareto(s),
            "hhi_window": ml.value("seller_hhi", start=START, end=WINDOW_END),
            "top10pct_share_window": ml.value(
                "seller_top10pct_gmv_share", start=START, end=WINDOW_END
            ),
            "fix_first_sellers": fix_first.head(15)[
                [
                    "seller_id",
                    "seller_state",
                    "orders",
                    "gmv_brl",
                    "on_time_rate",
                    "missed_handover_rate",
                    "avg_review",
                    "low_review_share",
                    "cancel_share",
                ]
            ],
            "fix_first_gmv_brl": float(fix_first.gmv_brl.sum()),
            "fix_first_low_reviews": float((fix_first.low_review_share * fix_first.orders).sum()),
            "scorecard_top25_by_gmv": s.sort_values("gmv_brl", ascending=False).head(25),
            "marketing_funnel_by_origin": funnel,
        },
    )
    write_report(
        "lanes",
        {
            "window": f"{START}..{WINDOW_END}",
            "min_orders": MIN_LANE_ORDERS,
            "summary": lanes_total,
            "worst_lanes": ln.head(15),
            "all_lanes": ln,
        },
    )
    s.to_csv(REPORTS / "seller_scorecard.csv", index=False)
    print(tiers.to_string())
    print(pareto(s)["top_10pct_sellers_share"], pareto(s)["share_of_sellers_for_80pct_gmv"])
    print(lanes_total)
    print(
        ln.head(8)[
            [
                "lane",
                "delivered_orders",
                "late_rate",
                "excess_late_orders",
                "late_share_seller_handover_missed",
            ]
        ].to_string()
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
