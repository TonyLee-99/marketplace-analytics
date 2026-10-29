"""(f) KPI anomaly detection on the daily series, as a BI monitoring job would run it.

Two detectors on the governed daily `orders` and `gmv` (metrics layer, day grain):

1. Retrospective: STL (weekly seasonality, robust) on log(value); robust z of the residual
   (median / 1.4826*MAD). Good for labelling history.
2. Online (what would have paged someone that day): for each day t, STL is fitted on the
   trailing 84 days ending t-1 only; the expected value for t = last trend + same-weekday
   seasonal; z = (forecast error_t - median) / (1.4826*MAD) of the previous 56 days'
   forecast errors. No look-ahead.

Alerting rule (both detectors):  |z| >= 4  on orders OR gmv  -> alert
                                  3 <= |z| < 4 on both metrics on the same day -> alert
Alerts on dates within +-1 day of a known calendar event (seeds/retail_events.csv, e.g.
Black Friday) are labelled `expected_event` (annotate the dashboard, do not page).

Run: python -m marketplace.analysis.anomalies
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from marketplace.analysis.common import WINDOW_END, df, write_report
from marketplace.metrics import MetricsLayer

START = "2017-01-01"
Z_HARD, Z_SOFT = 4.0, 3.0
ONLINE_LOOKBACK = 84
ERROR_WINDOW = 56
METRICS = ("orders", "gmv")


def robust_z(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    return (x - med) / mad


def daily_series(ml: MetricsLayer) -> pd.DataFrame:
    s = ml.compute(list(METRICS), grain="day", start=START, end=WINDOW_END)
    s.index = pd.to_datetime(s.index)
    full = pd.date_range(START, WINDOW_END, freq="D")
    return s.reindex(full).fillna(0)


def retrospective(s: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=s.index)
    for m in METRICS:
        y = np.log1p(s[m])
        res = STL(y, period=7, robust=True).fit()
        out[f"{m}_z"] = robust_z(res.resid)
        out[f"{m}_expected"] = np.expm1(res.trend + res.seasonal)
    return out


def online(s: pd.DataFrame) -> pd.DataFrame:
    """One-step-ahead forecasts from STL on the trailing window, scored against the robust
    scale of the PREVIOUS forecast errors (in-sample STL residuals understate how wrong a
    forecast is, which made a first version alert on 214 of 520 days)."""
    rows = []
    for t in range(ONLINE_LOOKBACK, len(s)):
        rec = {"date": s.index[t]}
        for m in METRICS:
            hist = np.log1p(s[m].iloc[t - ONLINE_LOOKBACK : t])
            fit = STL(hist, period=7, robust=True).fit()
            expected = fit.trend.iloc[-1] + fit.seasonal.iloc[-7]
            rec[f"{m}_err"] = np.log1p(s[m].iloc[t]) - expected
            rec[f"{m}_expected"] = np.expm1(expected)
        rows.append(rec)
    out = pd.DataFrame(rows).set_index("date")
    for m in METRICS:
        e = out[f"{m}_err"]
        past = e.shift(1).rolling(ERROR_WINDOW, min_periods=28)
        med = past.median()
        mad = (e.shift(1) - med).abs().rolling(ERROR_WINDOW, min_periods=28).median() * 1.4826
        out[f"{m}_z"] = (e - med) / mad
    return out.dropna(subset=["orders_z", "gmv_z"])


def apply_rule(z: pd.DataFrame, s: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    zo, zg = z["orders_z"], z["gmv_z"]
    hard = (zo.abs() >= Z_HARD) | (zg.abs() >= Z_HARD)
    soft = (zo.abs() >= Z_SOFT) & (zg.abs() >= Z_SOFT)
    alerts = z[hard | soft].copy()
    alerts["orders"] = s.loc[alerts.index, "orders"]
    alerts["gmv"] = s.loc[alerts.index, "gmv"]
    alerts["direction"] = np.where(alerts["orders_z"] + alerts["gmv_z"] > 0, "spike", "drop")
    ev = events.set_index("event_date")["event_name"]
    ev.index = pd.to_datetime(ev.index)

    def label(d):
        near = [n for e, n in ev.items() if abs((d - e).days) <= 1]
        return near[0] if near else None

    alerts["known_event"] = [label(d) for d in alerts.index]
    alerts["classification"] = np.where(
        alerts["known_event"].notna(), "expected_event", "investigate"
    )
    return alerts


def main() -> int:
    ml = MetricsLayer.load()
    s = daily_series(ml)
    events = df("select event_date, event_name from reference.retail_events")
    retro = retrospective(s)
    onl = online(s)
    a_retro = apply_rule(retro, s, events)
    a_onl = apply_rule(onl, s, events)
    bf = pd.Timestamp("2017-11-24")
    bf_block = {
        "orders": float(s.loc[bf, "orders"]),
        "gmv": float(s.loc[bf, "gmv"]),
        "orders_expected_retro": float(retro.loc[bf, "orders_expected"]),
        "orders_z_retro": float(retro.loc[bf, "orders_z"]),
        "orders_z_online": float(onl.loc[bf, "orders_z"]),
        "gmv_z_online": float(onl.loc[bf, "gmv_z"]),
        "flagged_retro": bool(bf in a_retro.index),
        "flagged_online": bool(bf in a_onl.index),
        "classification": a_onl.loc[bf, "classification"] if bf in a_onl.index else None,
        "multiple_of_expected_orders": float(
            s.loc[bf, "orders"] / retro.loc[bf, "orders_expected"]
        ),
        "handling": "Black Friday is in the event calendar: the alert fires (so the monitor is "
        "proven sensitive) but is classified expected_event and annotated rather than paged. "
        "The STL is robust (bisquare weights), so the spike does not drag the trend and mask "
        "the following days.",
    }
    week_after = s.loc["2017-11-25":"2017-11-30", "orders"]
    write_report(
        "anomalies",
        {
            "rule": f"|z|>={Z_HARD} on orders or gmv, or |z|>={Z_SOFT} on both; "
            "known events +-1 day -> expected_event",
            "daily_series_days": int(len(s)),
            "zero_order_days": int((s["orders"] == 0).sum()),
            "retrospective_alerts": a_retro.reset_index(names="date"),
            "online_alerts": a_onl.reset_index(names="date"),
            "n_retro_alerts": int(len(a_retro)),
            "n_online_alerts": int(len(a_onl)),
            "n_online_investigate": int((a_onl.classification == "investigate").sum()),
            "black_friday_2017": bf_block,
            "post_black_friday_orders_mean": float(week_after.mean()),
            "series": s.join(retro[["orders_z", "orders_expected"]])
            .join(onl[["orders_z"]].rename(columns={"orders_z": "orders_z_online"}))
            .reset_index(names="date"),
        },
    )
    print(f"retro alerts {len(a_retro)}, online alerts {len(a_onl)}")
    print(
        a_onl[["orders", "orders_z", "gmv_z", "direction", "classification", "known_event"]]
        .round(2)
        .to_string()
    )
    print(bf_block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
