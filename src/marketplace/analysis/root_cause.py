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
DIMENSIONS = ["customer_state", "category", "seller_tier"]
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


def decompose(ml: MetricsLayer, kpi: str, dim: str, m0: str, m1: str) -> dict:
    by = "primary_seller_id" if dim == "seller_tier" else dim
    comp = ml.components(
        kpi, by=by, grain="month", start=m0, end=pd.Timestamp(m1) + pd.offsets.MonthEnd(0)
    )
    comp["period"] = pd.to_datetime(comp["period"]).dt.strftime("%Y-%m-%d")
    comp = comp[comp.period.isin([m0, m1])]
    if dim == "seller_tier":
        tiers = seller_tiers(m0)
        comp["segment"] = comp["segment"].map(tiers).fillna("new_seller")
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
        w0, w1 = d0 / d0.sum(), d1 / d1.sum()
        r0 = n0 / d0.replace(0, np.nan)
        r1 = n1 / d1.replace(0, np.nan)
        # Segments absent in one period: use the other period's rate (contributes via mix only)
        r0f, r1f = r0.fillna(r1).fillna(0), r1.fillna(r0).fillna(0)
        total0, total1 = n0.sum() / d0.sum(), n1.sum() / d1.sum()
        # Centred mix term: moving share INTO a segment helps only if that segment is better
        # than the overall average. Sums to the same total as dw * r0 because sum(dw) = 0,
        # but the per-segment numbers are interpretable.
        mix = (w1 - w0) * (r0f - total0)
        rate = w0 * (r1f - r0f)
        inter = (w1 - w0) * (r1f - r0f)
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
        for m0, m1, z in find_moves(ml, kpi):
            dims = {dim: decompose(ml, kpi, dim, m0, m1) for dim in DIMENSIONS}
            h = headline(kpi, m0, m1, dims)
            ranked = sorted(dims, key=lambda d: dims[d]["surprise_js"], reverse=True)
            results.append(
                {
                    "kpi": kpi,
                    "from_month": m0,
                    "to_month": m1,
                    "robust_z_of_change": z,
                    "headline": h,
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
