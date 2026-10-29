"""What is a 1-2 star review worth in BRL? A seller-week panel.

For every seller-week (2017-03..2018-07) we relate the number of 1-2 star reviews the seller
received in the trailing 4 weeks to the seller's GMV in the NEXT 4 weeks, holding volume
fixed (trailing 4-week reviews and GMV) with seller and week fixed effects, SEs clustered by
seller. This is the "displayed rating -> other buyers" channel that repurchase analysis
cannot see. It is an association with strong controls, not an experiment: a seller in
trouble (stockouts) gets bad reviews AND sells less. Treat the estimate as an upper bound on
the causal cost of a bad review.

Run: python -m marketplace.analysis.review_value
"""

from __future__ import annotations

import sys

import pandas as pd
import pyfixest as pf

from marketplace.analysis.common import df, write_report


def panel() -> pd.DataFrame:
    gmv = df(
        """
        select seller_id, cast(date_trunc('week', purchase_date) as date) wk, sum(price_brl)::double gmv
        from marts.fct_order_items where is_revenue_order
          and purchase_date between '2017-01-02' and '2018-08-26'
        group by 1, 2
        """
    )
    rev = df(
        """
        select primary_seller_id seller_id, cast(date_trunc('week', review_answered_at) as date) wk,
               count(*) n_rev, count(*) filter (where review_score <= 2) n_bad
        from marts.fct_orders where is_revenue_order and review_score is not null
          and review_answered_at between '2017-01-02' and '2018-08-26'
        group by 1, 2
        """
    )
    weeks = pd.date_range("2017-01-02", "2018-08-20", freq="W-MON")
    sellers = gmv.seller_id.unique()
    idx = pd.MultiIndex.from_product([sellers, weeks], names=["seller_id", "wk"])
    p = pd.DataFrame(index=idx).reset_index()
    for t in (gmv, rev):
        t["wk"] = pd.to_datetime(t["wk"])
        p = p.merge(t, on=["seller_id", "wk"], how="left")
    p = p.fillna(0).sort_values(["seller_id", "wk"])
    g = p.groupby("seller_id")
    for c in ("gmv", "n_rev", "n_bad"):
        p[f"{c}_trail4"] = g[c].transform(lambda s: s.rolling(4, min_periods=4).sum())
    p["gmv_next4"] = g["gmv"].transform(lambda s: s[::-1].rolling(4, min_periods=4).sum()[::-1].shift(-1))
    p = p[(p.wk >= "2017-03-06") & (p.wk <= "2018-07-23")].dropna()
    # active sellers only: sold in the trailing 4 weeks
    p = p[p.gmv_trail4 > 0].copy()
    p["week"] = p["wk"].dt.strftime("%Y-%m-%d")
    return p


def main() -> int:
    p = panel()
    vc = {"CRV1": "seller_id"}
    fit = pf.feols("gmv_next4 ~ n_bad_trail4 + n_rev_trail4 + gmv_trail4 | seller_id + week", data=p, vcov=vc)
    t = fit.tidy().loc["n_bad_trail4"]
    share = pf.feols("np.log1p(gmv_next4) ~ I(n_bad_trail4 / n_rev_trail4) + np.log1p(n_rev_trail4) + "
                     "np.log1p(gmv_trail4) | seller_id + week",
                     data=p[p.n_rev_trail4 > 0], vcov=vc)
    ts = share.tidy().iloc[0]
    est = float(t["Estimate"])
    res = {
        "panel": {"seller_weeks": int(len(p)), "sellers": int(p.seller_id.nunique()),
                  "weeks": "2017-03..2018-07 (active seller-weeks)"},
        "brl_next4w_gmv_per_extra_bad_review": {
            "estimate": est, "se": float(t["Std. Error"]),
            "ci95": [float(t["2.5%"]), float(t["97.5%"])], "p": float(t["Pr(>|t|)"])},
        "log_gmv_on_bad_share": {"estimate": float(ts["Estimate"]), "ci95": [float(ts["2.5%"]), float(ts["97.5%"])],
                                 "p": float(ts["Pr(>|t|)"])},
        "significant_negative": bool(t["97.5%"] < 0),
        "reading": "Seller and week FE, volume controls; association, likely an upper bound on the causal "
        "cost (troubled sellers both get bad reviews and sell less). Used to price 1-2 star reviews in the "
        "promise and lane trade-offs, with its CI.",
    }
    write_report("review_value", res)
    print(res["brl_next4w_gmv_per_extra_bad_review"], res["log_gmv_on_bad_share"], res["panel"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
