"""(H4) Automated KPI root cause: "why did GMV / on-time / review score move?"

Mirrors the dimension-contribution approach of LinkedIn ThirdEye and Uber's root-cause
tooling, on top of the governed metrics layer (components come from MetricsLayer, so the
totals always equal the dashboard KPI).

For a ratio KPI  R = sum_i w_i * r_i   (w_i = segment share of the denominator):
    dR = sum_i dw_i * r_i0        (MIX: traffic moved between segments)
       + sum_i w_i0 * dr_i        (RATE: segments themselves got better/worse)
       + sum_i dw_i * dr_i        (INTERACTION)
which adds up exactly. Per segment the mix term is centred, dw_i * (r_i0 - R0), so a share
shift only "counts" if it moves volume toward a better- or worse-than-average segment. For an additive KPI (GMV) each segment's contribution is simply its
own change. Segments are ranked by |contribution|; a Simpson's-paradox flag is raised when
the aggregate moves in the opposite direction to the within-segment (rate) effect.

KPI moves to explain are found automatically: the largest month-over-month changes (by
robust z-score) of each KPI in the reliable window.

Run: python -m marketplace.analysis.root_cause
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from marketplace.analysis.common import WINDOW_END, df, write_report
from marketplace.metrics import MetricsLayer

KPIS = ["gmv", "on_time_delivery_rate", "avg_review_score"]
DIMENSIONS = ["customer_state", "category", "seller_tier", "seller_state", "lane_top", "fulfilment_leg"]
NETWORK_WIDE_VOLUME_SHARE = 0.8
TOP_MOVES = 2


def seller_tiers(before: str) -> pd.Series:
    """Tier sellers on GMV earned BEFORE the period (no look-ahead): A = top 10% of active
    sellers, B = next 40%, C = rest; sellers with no prior sales = 'new'."""
    g = df(
        f"""
        select seller_id, sum(price_brl) as gmv
        from marts.fct_order_items
        where is_revenue_order and purchase_date < '{before}'
        group by 1
        """
    ).sort_values("gmv", ascending=False)
    n = len(g)
    rank = np.arange(n)
    tier = np.where(
        rank < np.ceil(0.1 * n),
        "A_top10pct",
        np.where(rank < np.ceil(0.5 * n), "B_next40pct", "C_bottom50pct"),
    )
    return pd.Series(tier, index=g["seller_id"])


def _js(p: pd.Series, q: pd.Series) -> float:
    """Jensen-Shannon divergence between two share vectors (Adtributor 'surprise')."""
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2

    def kl(a, b):
        mask = a > 0
        return float((a[mask] * np.log2(a[mask] / b[mask])).sum())

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def mix_rate_split(n0: pd.Series, d0: pd.Series, n1: pd.Series, d1: pd.Series) -> dict:
    """Pure maths of the ratio decomposition R = sum(w_i r_i): centred mix, rate, interaction."""
    w0, w1 = d0 / d0.sum(), d1 / d1.sum()
    r0 = n0 / d0.replace(0, np.nan)
    r1 = n1 / d1.replace(0, np.nan)
    # Segments absent in one period: use the other period's rate (contributes via mix only)
    r0f, r1f = r0.fillna(r1).fillna(0), r1.fillna(r0).fillna(0)
    total0, total1 = n0.sum() / d0.sum(), n1.sum() / d1.sum()
    # Centred mix term: moving share INTO a segment helps only if that segment beats the
    # average. Same total as dw * r0 because sum(dw) = 0, but per-segment values are readable.
    mix = (w1 - w0) * (r0f - total0)
    rate = w0 * (r1f - r0f)
    inter = (w1 - w0) * (r1f - r0f)
    return {"w0": w0, "w1": w1, "r0": r0, "r1": r1, "mix": mix, "rate": rate, "inter": inter,
            "total0": total0, "total1": total1}


TOP_LANES = 15


def decompose(ml: MetricsLayer, kpi: str, dim: str, m0: str, m1: str) -> dict:
    by = {"seller_tier": "primary_seller_id", "lane_top": "lane"}.get(dim, dim)
    comp = ml.components(
        kpi, by=by, grain="month", start=m0, end=pd.Timestamp(m1) + pd.offsets.MonthEnd(0)
    )
    comp["period"] = pd.to_datetime(comp["period"]).dt.strftime("%Y-%m-%d")
    comp = comp[comp.period.isin([m0, m1])]
    if dim == "seller_tier":
        tiers = seller_tiers(m0)
        comp["segment"] = comp["segment"].map(tiers).fillna("new_seller")
        comp = comp.groupby(["period", "segment"], as_index=False)[["num", "den"]].sum(min_count=1)
    if dim == "lane_top":
        vol = comp.groupby("segment")["num" if ml.metrics[kpi]["type"] == "simple" else "den"].sum()
        top = set(vol.sort_values(ascending=False).head(TOP_LANES).index)
        comp["segment"] = comp["segment"].where(comp["segment"].isin(top), "other lanes")
        comp = comp.groupby(["period", "segment"], as_index=False)[["num", "den"]].sum(min_count=1)
    comp["segment"] = comp["segment"].fillna("unknown")
    wide = comp.pivot_table(
        index="segment", columns="period", values=["num", "den"], aggfunc="sum"
    ).fillna(0)
    n0, n1 = wide[("num", m0)], wide[("num", m1)]
    additive = ml.metrics[kpi]["type"] == "simple" and ml.metrics[kpi]["measure"]["agg"] != "avg"
    if additive:
        total0, total1 = n0.sum(), n1.sum()
        contrib = n1 - n0
        seg = pd.DataFrame({"value_from": n0, "value_to": n1, "contribution": contrib})
        res = {
            "kpi_from": total0,
            "kpi_to": total1,
            "delta": total1 - total0,
            "mix_effect": None,
            "rate_effect": None,
            "interaction": None,
            "surprise_js": _js(n0.clip(lower=0), n1.clip(lower=0)),
        }
    else:
        d0, d1 = wide[("den", m0)], wide[("den", m1)]
        mr = mix_rate_split(n0, d0, n1, d1)
        w0, w1, r0, r1 = mr["w0"], mr["w1"], mr["r0"], mr["r1"]
        mix, rate, inter = mr["mix"], mr["rate"], mr["inter"]
        total0, total1 = mr["total0"], mr["total1"]
        seg = pd.DataFrame(
            {
                "share_from": w0,
                "share_to": w1,
                "rate_from": r0,
                "rate_to": r1,
                "n_from": d0,
                "n_to": d1,
                "mix": mix,
                "rate": rate,
                "interaction": inter,
                "contribution": mix + rate + inter,
            }
        )
        res = {
            "kpi_from": total0,
            "kpi_to": total1,
            "delta": total1 - total0,
            "mix_effect": float(mix.sum()),
            "rate_effect": float(rate.sum()),
            "interaction": float(inter.sum()),
            # Adtributor-style surprise for a derived measure: numerator + denominator shifts
            "surprise_js": _js(n0.clip(lower=0), n1.clip(lower=0))
            + _js(d0.clip(lower=0), d1.clip(lower=0)),
        }
        res["residual"] = res["delta"] - (
            res["mix_effect"] + res["rate_effect"] + res["interaction"]
        )
        # Simpson check: does the aggregate move against the within-segment effect?
        res["simpson_paradox"] = bool(
            np.sign(res["delta"]) != np.sign(res["rate_effect"]) and abs(res["rate_effect"]) > 1e-9
        )
        res["share_of_segments_improving"] = float(
            (d0[(r1 > r0)].sum()) / d0[r0.notna() & r1.notna()].sum()
        )
    seg = seg.reset_index().rename(columns={"index": "segment"})
    seg["abs_contribution"] = seg["contribution"].abs()
    seg = seg.sort_values("abs_contribution", ascending=False)
    total_abs = seg["abs_contribution"].sum()
    seg["share_of_abs_movement"] = seg["abs_contribution"] / total_abs if total_abs else 0
    res["top_segments"] = seg.head(8).drop(columns="abs_contribution")
    res["n_segments"] = int(len(seg))
    # Explanatory power: share of |movement| explained by top-3 segments.
    res["top3_share_of_abs_movement"] = float(seg["share_of_abs_movement"].head(3).sum())
    return res


def find_moves(ml: MetricsLayer, kpi: str) -> list[tuple[str, str, float]]:
    s = ml.compute([kpi], grain="month", start="2017-01-01", end=WINDOW_END)[kpi]
    s.index = pd.to_datetime(s.index)
    ch = s.pct_change() if kpi == "gmv" else s.diff()
    ch = ch.dropna()
    # Robust z of each MoM change vs the typical MoM change
    med, mad = ch.median(), (ch - ch.median()).abs().median() * 1.4826
    z = (ch - med) / mad
    # Ignore the 2017 ramp-up months for GMV (platform launch growth is not an anomaly)
    if kpi == "gmv":
        z = z[z.index >= "2017-06-01"]
    picks = z.abs().sort_values(ascending=False).head(TOP_MOVES).index
    out = []
    for ts in sorted(picks):
        prev = ts - pd.DateOffset(months=1)
        out.append((prev.strftime("%Y-%m-%d"), ts.strftime("%Y-%m-%d"), float(z[ts])))
    return out


def verdict(kpi: str, dims: dict) -> dict:
    """Ops answer: name a driver only when one exists; otherwise say network-wide."""
    best = max(dims, key=lambda d: dims[d]["surprise_js"])
    d = dims[best]
    if d.get("rate_effect") is None:
        top = d["top_segments"].iloc[0]
        return {"type": "segment", "dimension": best, "segment": str(top["segment"]),
                "text": f"largest contributor: {best} = {top['segment']}"}
    same_dir = []
    for v in dims.values():
        if v.get("share_of_segments_improving") is None:
            continue
        share = v["share_of_segments_improving"] if v["delta"] > 0 else 1 - v["share_of_segments_improving"]
        same_dir.append(share)
    broad = min(same_dir) if same_dir else 0
    rate_dominant = abs(d["rate_effect"]) >= 0.8 * abs(d["delta"])
    if rate_dominant and broad >= NETWORK_WIDE_VOLUME_SHARE:
        return {"type": "network_wide", "share_of_volume_moving_with_kpi_min_over_dims": broad,
                "text": "network-wide: no single segment driver (the move happened inside "
                f"segments holding >= {broad:.0%} of volume in every dimension)"}
    top = d["top_segments"].iloc[0]
    return {"type": "segment", "dimension": best, "segment": str(top["segment"]),
            "text": f"concentrated: {best} = {top['segment']}"}


def stage_shapley(m0: str, m1: str) -> dict:
    """On-time move split by process stage: promise length, seller stage (purchase -> carrier),
    carrier transit. Each stage of month m1 is shifted to its m0 median level; Shapley values
    over the 2^3 combinations add up to the explained part of the late-rate change."""
    from itertools import combinations
    from math import factorial

    q = df(
        f"""
        select purchase_month m, promised_days::double promise,
               date_diff('day', purchase_date, cast(delivered_to_customer_at as date))::double y,
               (epoch(delivered_to_carrier_at) - epoch(purchased_at)) / 86400.0 seller_days,
               carrier_transit_days transit
        from marts.fct_orders
        where is_delivered and is_revenue_order and purchase_month in ('{m0}', '{m1}')
          and delivered_to_carrier_at is not null
        """
    )
    q["m"] = pd.to_datetime(q["m"]).dt.strftime("%Y-%m-%d")
    a, b = q[q.m == m0], q[q.m == m1]
    med = {k: (float(a[k].median()), float(b[k].median())) for k in ("promise", "seller_days", "transit")}
    shift = {"promise": med["promise"][0] - med["promise"][1],
             "seller_days": med["seller_days"][0] - med["seller_days"][1],
             "transit": med["transit"][0] - med["transit"][1]}

    def late(S):
        y = b["y"] + sum(shift[k] for k in S if k != "promise")
        p = b["promise"] + (shift["promise"] if "promise" in S else 0)
        return float(np.mean(y > p))

    factors = list(shift)
    n = len(factors)
    phi = {}
    for f in factors:
        others = [x for x in factors if x != f]
        v = 0.0
        for k in range(n):
            for S in combinations(others, k):
                w = factorial(len(S)) * factorial(n - len(S) - 1) / factorial(n)
                v += w * (late(set(S)) - late(set(S) | {f}))
        phi[f] = v  # contribution of factor f to (late_m1 - late_counterfactual_all_shifted)
    late0, late1 = float(np.mean(a.y > a.promise)), late(set())
    explained = late1 - late(set(factors))
    return {"medians_from_to": med, "late_rate_from": late0, "late_rate_to": late1,
            "shapley_pp": {k: 100 * v for k, v in phi.items()}, "explained_pp": 100 * explained,
            "unexplained_pp_distribution_shape": 100 * ((late1 - late0) - explained),
            "reading": "Positive = this stage's change raised the late rate."}


def headline(kpi: str, m0: str, m1: str, dims: dict) -> str:
    # Rank dimensions by surprise (how differently the segments moved), not by top-3 share,
    # which mechanically favours dimensions with few segments.
    best_dim = max(dims, key=lambda d: dims[d]["surprise_js"])
    top = dims[best_dim]["top_segments"].iloc[0]
    d = dims[best_dim]
    s = (
        f"{kpi} {m0[:7]} -> {m1[:7]}: {d['kpi_from']:.4g} -> {d['kpi_to']:.4g}. "
        f"Most surprising dimension: {best_dim} (top-3 segments = "
        f"{d['top3_share_of_abs_movement']:.0%} of movement); #1 = {top['segment']} "
        f"({top['contribution']:+.4g})"
    )
    if d.get("mix_effect") is not None:
        s += (
            f"; rate effect {d['rate_effect']:+.4f}, mix effect {d['mix_effect']:+.4f}, "
            f"segments (by volume) improving {d['share_of_segments_improving']:.0%}"
            + (" [SIMPSON]" if d["simpson_paradox"] else "")
        )
    return s


def main() -> int:
    ml = MetricsLayer.load()
    results = []
    for kpi in KPIS:
        moves = find_moves(ml, kpi)
        if kpi == "on_time_delivery_rate":  # the Feb-Mar 2018 slowdown, end to end
            moves.append(("2018-01-01", "2018-03-01", float("nan")))
        for m0, m1, z in moves:
            dims = {dim: decompose(ml, kpi, dim, m0, m1) for dim in DIMENSIONS}
            h = headline(kpi, m0, m1, dims)
            v = verdict(kpi, dims)
            ranked = sorted(dims, key=lambda d: dims[d]["surprise_js"], reverse=True)
            results.append(
                {
                    "kpi": kpi,
                    "from_month": m0,
                    "to_month": m1,
                    "robust_z_of_change": z,
                    "headline": h,
                    "verdict": v,
                    "stages": stage_shapley(m0, m1) if kpi == "on_time_delivery_rate" else None,
                    "dimension_ranking_by_surprise": ranked,
                    "by_dimension": dims,
                }
            )
            print(h)
    # Simpson scan: every consecutive month pair, every ratio KPI x dimension.
    scan = []
    months = pd.date_range("2017-02-01", "2018-08-01", freq="MS")
    for kpi in ("on_time_delivery_rate", "avg_review_score"):
        for ts in months:
            m0 = (ts - pd.DateOffset(months=1)).strftime("%Y-%m-%d")
            m1 = ts.strftime("%Y-%m-%d")
            for dim in DIMENSIONS:
                r = decompose(ml, kpi, dim, m0, m1)
                scan.append(
                    {
                        "kpi": kpi,
                        "month": m1[:7],
                        "dimension": dim,
                        "delta": r["delta"],
                        "rate_effect": r["rate_effect"],
                        "mix_effect": r["mix_effect"],
                        "simpson_paradox": r["simpson_paradox"],
                    }
                )
    scan_df = pd.DataFrame(scan)
    print(
        f"Simpson scan: {int(scan_df.simpson_paradox.sum())} of {len(scan_df)} "
        "KPI-month-dimension cases"
    )
    write_report(
        "root_cause",
        {
            "simpson_scan": {
                "n_cases": len(scan_df),
                "n_simpson": int(scan_df.simpson_paradox.sum()),
                "cases": scan_df[scan_df.simpson_paradox],
                # Material = the hidden within-segment movement is at least 0.5 pp (on-time) or
                # 0.02 stars (review); smaller reversals are noise around a flat aggregate.
                "n_material_simpson": int(
                    (
                        scan_df.simpson_paradox
                        & (
                            scan_df.rate_effect.abs()
                            >= np.where(scan_df.kpi == "avg_review_score", 0.02, 0.005)
                        )
                    ).sum()
                ),
                "max_abs_delta_among_simpson_cases": float(
                    scan_df.loc[scan_df.simpson_paradox, "delta"].abs().max()
                ),
            },
            "method": "mix/rate/interaction decomposition over the governed metric components",
            "dimensions": DIMENSIONS,
            "moves": results,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
