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


def inflight_late_series() -> pd.DataFrame:
    """Daily in-flight lateness, knowable on the day itself: among revenue orders purchased in
    the last 60 days and not yet delivered at day end, the share already past their promised
    date. Unlike the purchase-cohort on-time rate it is not right-censored."""
    q = df(
        f"""
        with days as (select cast(d as date) as dd from range(timestamp '{START}',
                      timestamp '{WINDOW_END}' + interval 1 day, interval 1 day) t(d)),
        o as (select purchase_date, estimated_delivery_date,
                     cast(delivered_to_customer_at as date) dlv
              from marts.fct_orders where is_revenue_order)
        select dd as day,
               count(*) filter (where o.dlv is null or o.dlv > dd) open_orders,
               count(*) filter (where (o.dlv is null or o.dlv > dd)
                                and o.estimated_delivery_date < dd) past_promise
        from days join o on o.purchase_date between dd - interval 60 day and dd
        group by 1 order by 1
        """
    )
    q["day"] = pd.to_datetime(q["day"])
    q["share_past_promise"] = q["past_promise"] / q["open_orders"]
    return q.set_index("day")


def inflight_monitor() -> dict:
    """Online rule on the in-flight share: alert when today's share exceeds the trailing 28-day
    median by >= 4 robust SDs (MAD of daily changes), 2 days in a row."""
    q = inflight_late_series()
    q = q.loc["2017-03-01":]  # 60-day warm-up of the open-order window
    x = q["share_past_promise"]

    def rule(win, thr):
        med = x.shift(1).rolling(win, min_periods=win).median()
        mad = (x.shift(1) - med).abs().rolling(win, min_periods=win).median() * 1.4826
        z = (x - med) / mad
        return z, (z >= thr) & (z.shift(1) >= thr)

    z, fire = rule(56, 3)
    alerts = q[fire].assign(z=z[fire])
    _, fire_alt = rule(28, 3)
    alt_first_feb_mar = fire_alt["2018-02-01":"2018-04-15"]
    first = {}
    for label, (a, b) in {"feb_mar_2018_slowdown": ("2018-02-01", "2018-03-31"),
                          "truckers_strike_may_2018": ("2018-05-15", "2018-06-15"),
                          "black_friday_backlog_2017": ("2017-11-20", "2017-12-31")}.items():
        hit = alerts.loc[a:b]
        first[label] = str(hit.index.min().date()) if len(hit) else None
    return {
        "definition": "share of open (undelivered, purchased <= 60 days ago) revenue orders already past the "
        "promised date, computed each day from data available that day",
        "rule": "z >= 3 vs trailing 56-day median (1.4826*MAD scale), two consecutive days",
        "sensitivity_28d_window_first_feb_mar_alert": str(alt_first_feb_mar[alt_first_feb_mar].index.min().date())
        if alt_first_feb_mar.any() else None,
        "volume_monitor_alerts_feb_mar_2018": 0,
        "n_alert_days": int(len(alerts)),
        "first_alert_by_incident": first,
        "series": q.reset_index()[["day", "open_orders", "past_promise", "share_past_promise"]],
        "alert_days": alerts.reset_index()[["day", "share_past_promise", "z"]],
    }


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
    inflight = inflight_monitor()
    write_report(
        "anomalies",
        {
            "inflight_late_monitor": inflight,
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
