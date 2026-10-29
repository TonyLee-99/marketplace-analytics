"""Build the self-contained executive dashboard (dashboard/index.html).

Data flow:  marts --(metrics layer)--> additive cubes + metric values --> JSON --> one HTML
file with plotly.js inlined (works offline, no CDN).  Analysis outputs come from
reports/*.json, which were themselves computed from the marts / metrics layer.

The dashboard never defines a KPI formula. Ratio KPIs are shipped as additive
(numerator, denominator) components from MetricsLayer.components(); the browser only sums
components for the selected filters and divides, and evaluates derived metrics with the
`formula` string from metrics.yml.

Run: python -m marketplace.dashboard.build
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly

from marketplace.analysis.common import WINDOW_END, WINDOW_START, _clean, read_report
from marketplace.metrics import MetricsLayer
from marketplace.paths import DASHBOARD_DIR, REPORTS

HERE = Path(__file__).parent
CUBE_METRICS = [
    "gmv",
    "orders",
    "on_time_delivery_rate",
    "avg_review_score",
    "pct_5_star",
    "pct_1_2_star",
    "freight_to_price_ratio",
    "cancellation_rate",
    "avg_days_vs_promise",
    "avg_delivery_days",
]
DERIVED = ["aov", "nps_style_score"]
TOP_CATEGORIES = 15


def build_cube(ml: MetricsLayer) -> dict:
    """Columnar cube: month x customer_state x category_group x metric -> (num, den)."""
    top = (
        ml.components("gmv", by="category", grain="all")
        .sort_values("num", ascending=False)["segment"]
        .head(TOP_CATEGORIES)
        .tolist()
    )
    frames = []
    for m in CUBE_METRICS:
        c = ml.components(
            m, by=["customer_state", "category"], grain="month", start=WINDOW_START, end=WINDOW_END
        )
        c["category"] = c["category"].where(c["category"].isin(top), "other")
        c = c.groupby(["period", "customer_state", "category"], as_index=False)[["num", "den"]].sum(
            min_count=1
        )
        c["metric"] = m
        frames.append(c)
    cube = pd.concat(frames)
    cube["period"] = pd.to_datetime(cube["period"]).dt.strftime("%Y-%m")
    months = sorted(cube["period"].unique())
    states = sorted(cube["customer_state"].dropna().unique())
    cats = top + ["other"]
    cube = cube.dropna(subset=["customer_state"])
    return {
        "months": months,
        "states": states,
        "categories": cats,
        "metrics": CUBE_METRICS,
        "m": cube["period"].map({v: i for i, v in enumerate(months)}).tolist(),
        "s": cube["customer_state"].map({v: i for i, v in enumerate(states)}).tolist(),
        "c": cube["category"].map({v: i for i, v in enumerate(cats)}).tolist(),
        "k": cube["metric"].map({v: i for i, v in enumerate(CUBE_METRICS)}).tolist(),
        "num": cube["num"].round(4).fillna(0).tolist(),
        "den": cube["den"].round(4).tolist(),
    }


def active_customers(ml: MetricsLayer, cube: dict) -> dict:
    """count_distinct is not additive, so ship it per single-dimension slice."""
    out = {"all": {}, "state": {}, "category": {}}
    s = ml.compute(["active_customers"], grain="month", start=WINDOW_START, end=WINDOW_END)
    out["all"] = {pd.Timestamp(k).strftime("%Y-%m"): v for k, v in s["active_customers"].items()}
    for st in cube["states"]:
        s = ml.compute(
            ["active_customers"],
            grain="month",
            where={"customer_state": st},
            start=WINDOW_START,
            end=WINDOW_END,
        )
        out["state"][st] = {
            pd.Timestamp(k).strftime("%Y-%m"): v for k, v in s["active_customers"].items()
        }
    for cat in cube["categories"]:
        if cat == "other":
            continue
        s = ml.compute(
            ["active_customers"],
            grain="month",
            where={"category": cat},
            start=WINDOW_START,
            end=WINDOW_END,
        )
        out["category"][cat] = {
            pd.Timestamp(k).strftime("%Y-%m"): v for k, v in s["active_customers"].items()
        }
    return out


def metric_meta(ml: MetricsLayer) -> dict:
    meta = {}
    for name, m in ml.metrics.items():
        meta[name] = {
            "label": m["label"],
            "unit": m["unit"],
            "definition": m["definition"].strip(),
            "owner": m["owner"],
            "target": m.get("target"),
            "formula": m.get("formula"),
            "type": m["type"],
        }
    return meta


def main() -> int:
    ml = MetricsLayer.load()
    cube = build_cube(ml)
    payload = {
        "built_from": "marts.* via metrics/metrics.yml + reports/*.json",
        "window": [WINDOW_START, WINDOW_END],
        "cube": cube,
        "derived": {d: ml.metrics[d]["formula"] for d in DERIVED},
        "active": active_customers(ml, cube),
        "meta": metric_meta(ml),
        "reports": {
            name: (read_report(name) if (REPORTS / f"{name}.json").exists() else {})
            for name in [
                "growth",
                "cohorts",
                "delivery_impact",
                "promise_policy",
                "sellers",
                "lanes",
                "anomalies",
                "root_cause",
                "voc",
                "metric_conflicts",
            ]
        },
    }
    # Trim heavy series not needed client-side.
    payload["reports"]["lanes"].pop("all_lanes", None)
    payload["reports"]["sellers"].pop("scorecard_top25_by_gmv", None)
    data_json = json.dumps(_clean(payload), separators=(",", ":"), default=str)
    plotly_js = (Path(plotly.__file__).parent / "package_data" / "plotly.min.js").read_text()
    html = (HERE / "template.html").read_text()
    html = html.replace("/*__PLOTLY__*/", plotly_js)
    html = html.replace("/*__DATA__*/", f"window.DATA = {data_json};")
    html = html.replace("/*__APP__*/", (HERE / "app.js").read_text())
    DASHBOARD_DIR.mkdir(exist_ok=True)
    out = DASHBOARD_DIR / "index.html"
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, data {len(data_json) / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
