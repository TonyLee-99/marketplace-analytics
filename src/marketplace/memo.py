"""Generate reports/recommendations.json and docs/exec_memo.md from the analysis reports.

The memo and the dashboard's decision panel read the SAME recommendations.json, so their
numbers cannot drift apart. Run: python -m marketplace.memo
"""

from __future__ import annotations

import json
import math
import sys

from marketplace.analysis.common import read_report
from marketplace.metrics import MetricsLayer
from marketplace.paths import DOCS, REPORTS

W0, W1 = "2017-01-01", "2018-08-31"


def pct(v, d=1):
    return f"{100 * v:.{d}f}%"


def brl(v):
    s = "−" if v < 0 else ""
    v = abs(v)
    return f"{s}R${v / 1e6:.2f}M" if v >= 1e6 else f"{s}R${v / 1e3:.0f}k" if v >= 1e4 else f"{s}R${v:,.0f}"


def build() -> dict:
    ml = MetricsLayer.load()
    g, di, pp = read_report("growth"), read_report("delivery_impact"), read_report("promise_policy")
    ln, voc, rv = read_report("lanes"), read_report("voc"), read_report("review_value")
    rc, s = read_report("root_cause"), read_report("sellers")
    sup = g["supply_side"]
    tree = sup["jun_aug_vs_mar_may_seller_tree"]
    lever = di["impact"]["survey_on_delivery_lever"]
    b = di["bounds"]["C_within_seller_month"]
    fy, sel, te = pp["policies"]["full_year"], pp["policies"]["selection"], pp["policies"]["test"]
    q80 = fy["lane_q80"]
    cap = fy.get("lane_q80_capped_5d", q80)
    cur = fy["current_olist_estimate"]
    stages = next(m for m in rc["moves"] if m["kpi"] == "on_time_delivery_rate"
                  and m["from_month"].startswith("2018-01") and m["to_month"].startswith("2018-03"))["stages"]
    rep = di["repurchase"]
    ot = voc["negative_on_time_share_corrected_for_misclassification"]
    inc_yr = voc["incomplete_order_1_2_star_reviews"] / voc["months_covered"] * 12
    t2 = next(t for t in s["tiers"] if t["tier"].startswith("T2"))
    # A/B guardrail MDE: all lanes, 4 weeks, 50/50 by customer (volume from the test months)
    orders_4w = pp["coverage"]["test"]["n"] / 5 * 12 / 13
    p_late = te["current_olist_estimate"]["late_rate"]
    n_arm = orders_4w / 2
    mde_late = 2.8 * math.sqrt(2 * p_late * (1 - p_late) / n_arm)
    recs = [
        {
            "id": 1,
            "title": "Send the review survey on confirmed delivery",
            "why": f"{pct(di['survey_timing']['late_answered_before_delivery_share'], 0)} of late orders are rated before they arrive.",
            "impact": f"≤ {lever['one_two_star_reviews_avoided_upper_bound']:,.0f} fewer 1–2★/yr; "
            f"+{lever['network_avg_review_gain']:.2f}★ network average (upper bounds)",
            "cost": "1 sprint (change the survey trigger event)",
            "confidence": "High on direction, medium on size",
            "owner": "CX product manager", "date": "ship by 2018-09-30",
        },
        {
            "id": 2,
            "title": "Don't roll out shorter promises. A/B-test a capped cut (lane-P80, at most 5 days shorter) outside peak season",
            "why": f"Full year: lane-P80 saves {q80['mean_days_saved_vs_current']:.1f} days but late rises "
            f"{pct(cur['late_rate'])} → {pct(q80['late_rate'])}. Oct–Mar, today's promise was already "
            f"{pct(sel['current_olist_estimate']['late_rate'])} late; the pre-set rule picks '{pp['recommended_policy'].replace('_', ' ')}', "
            "which lengthens peak promises.",
            "impact": f"Rollout cost +{q80['survey_today']['extra_1_2_star_reviews_per_year']:,.0f} 1–2★/yr today, "
            f"+{q80['survey_on_delivery']['extra_1_2_star_reviews_per_year']:,.0f} after #1. Break-even: "
            f"+{pct(q80['survey_today']['breakeven_conversion_lift_per_promise_day'], 3)} conversion per day saved. "
            f"A/B variant (capped): −{cap['mean_days_saved_vs_current']:.1f} d, late {pct(cap['late_rate'])}",
            "cost": "A/B test: 1 sprint + 4 weeks",
            "confidence": "Low: upside unmeasured",
            "owner": "Delivery-promise PM + analytics", "date": "start 2018-09-17, read out 2018-10-15 (before the Black Friday freeze)",
            "ab_design": {
                "unit": "customer (cookie), 50/50, all lanes; treatment promise = max(lane-P80, current - 5 days)",
                "primary_metric": "checkout conversion of sessions that saw a promise",
                "guardrails": "lane late rate <= 7% (never-delivered = late); 1–2★ share",
                "duration": "4 weeks",
                "guardrail_mde_late_rate_pp": 100 * mde_late,
                "orders_per_arm": n_arm,
                "kill_rule": "stop if treatment late rate exceeds control by 3 pp for 7 consecutive days, or 1–2★ share is +1 pp",
                "conversion_mde_note": "needs session counts (not in the Olist extract): MDE ≈ 2.8·sqrt(2c(1−c)/S) for conversion c and S sessions per arm",
            },
        },
        {
            "id": 3,
            "title": "Fix partial shipments: mark 'delivered' only when every item has arrived, and announce split shipments",
            "why": f"'Incomplete order' is a top-two complaint on ON-TIME orders ({pct(ot['incomplete_order']['corrected'], 0)}, "
            f"CI {pct(ot['incomplete_order']['ci95'][0], 0)}–{pct(ot['incomplete_order']['ci95'][1], 0)}); "
            f"{pct(voc['incomplete_order_reviews_on_multi_item_orders'], 0)} are multi-item orders "
            f"({pct(voc['all_text_reviews_on_multi_item_orders'], 0)} of reviews).",
            "impact": f"≤ {inc_yr:,.0f} 1–2★/yr on {brl(voc['incomplete_order_1_2_star_gmv_brl'] / voc['months_covered'] * 12)}/yr of orders "
            "(upper bound); raises the measured late rate",
            "cost": "product + seller ops",
            "confidence": "Medium (text classifier, silver labels)",
            "owner": "Marketplace ops + order-management engineering", "date": "scope by 2018-10-01",
        },
    ]
    demoted = [
        f"Seller quality plan for the {t2['sellers']} 'fix-first' sellers ({pct(t2['gmv_share'], 0)} of GMV, "
        f"{pct(t2['on_time'], 0)} on-time): ops hygiene, no measurable BRL.",
        f"Lane/carrier programme: against a lane-adjusted baseline (distance, destination, origin, month) the 10 worst lanes "
        f"have only {ln['summary']['top10_excess_late_orders']:,.0f} excess late orders/yr "
        f"(≈{ln['summary']['low_reviews_avoidable_top10']:.0f} 1–2★ recorded, "
        f"{ln['summary']['low_reviews_avoidable_top10_post_delivery']:.0f} post-delivery). That is down from "
        f"{ln['summary']['excess_vs_network_top10_old_method']:,.0f} against the network average. There is no carrier ID, so 'switch carrier' cannot be analysed.",
        f"Money on reviews: in a seller-week panel, one extra 1–2★ review is associated with "
        f"{brl(rv['brl_next4w_gmv_per_extra_bad_review']['estimate'])} of the seller's next-4-week GMV "
        f"(95% CI {brl(rv['brl_next4w_gmv_per_extra_bad_review']['ci95'][0])} to "
        f"{brl(rv['brl_next4w_gmv_per_extra_bad_review']['ci95'][1])}, p={rv['brl_next4w_gmv_per_extra_bad_review']['p']:.2f}): "
        "not detectable, so no BRL is attached to review gains.",
    ]
    net = {
        "late_orders_per_year": {"rec1": 0, "rec2_ab_only": "small (A/B on 10 lanes)",
                                 "rec2_if_rolled_out_lane_p80": q80["extra_late_orders_per_year"],
                                 "rec3": "raises measured late rate (not quantified: no item-level delivery timestamps)"},
        "one_two_star_per_year": {"rec1_upper_bound": -lever["one_two_star_reviews_avoided_upper_bound"],
                                  "rec2_rollout_survey_today": q80["survey_today"]["extra_1_2_star_reviews_per_year"],
                                  "rec2_rollout_after_rec1": q80["survey_on_delivery"]["extra_1_2_star_reviews_per_year"],
                                  "rec3_upper_bound": -inc_yr},
        "interactions": "Rec 1 cuts the review cost of Rec 2 by about "
        f"{1 - q80['survey_on_delivery']['extra_1_2_star_reviews_per_year'] / max(q80['survey_today']['extra_1_2_star_reviews_per_year'], 1):.0%}. "
        "Rec 3 delays the recorded delivery, which delays the survey under Rec 1 and raises the measured late rate. "
        "The effects are not additive; the lever sizes are upper bounds.",
    }
    state = {
        "gmv_window": ml.value("gmv", start=W0, end=W1),
        "orders_window": ml.value("orders", start=W0, end=W1),
        "on_time_window": ml.value("on_time_delivery_rate", start=W0, end=W1),
        "review_window": ml.value("avg_review_score", start=W0, end=W1),
        "plateau": sup["plateau"],
        "seller_tree": tree,
        "new_seller_gmv_share_2018": sup["new_seller_gmv_share_2018"],
        "funnel": sup["funnel"],
        "yoy_ytd": g["ytd_jan_aug_2018_vs_2017"]["pct_change"],
        "repeat_rate_distinct_days": ml.value("repeat_purchase_rate"),
        "late_effect_bounds_within_seller_month": b,
        "carrier_leg_post_delivery": di["E_carrier_leg_only"]["estimate"],
        "strike_iv_post_delivery": di["F_strike_iv"]["post_delivery_reviews"]["iv_late_effect"],
        "strike_iv_recorded": di["F_strike_iv"]["recorded_all_reviews"]["iv_late_effect"],
        "repurchase": {"effect_pp": 100 * rep["fe_lpm"]["estimate"], "mde_pp": 100 * rep["mde_80pct_power"],
                       "mde_rel": rep["mde_relative_to_base"], "base": rep["base_rate"]},
        "stages_jan_mar_2018": stages,
    }
    return {"window": [W0, W1], "state": state, "recommendations": recs, "demoted": demoted, "net": net}


def render(r: dict) -> str:
    st, rec, net = r["state"], r["recommendations"], r["net"]
    pl, tr = st["plateau"], st["seller_tree"]
    b = st["late_effect_bounds_within_seller_month"]
    sh = st["stages_jan_mar_2018"]["shapley_pp"]
    ab = rec[1]["ab_design"]
    lines = [
        "# Marketplace: state of the business and three decisions",
        "",
        f"**To:** VP Marketplace · **Data:** Olist public extract, orders {r['window'][0]} to {r['window'][1]} · "
        "**Read time:** 5 min · _Generated by `make memo` from reports/*.json; every number is listed in docs/RESULTS.md_",
        "",
        "## State of the business",
        f"- **Growth has stalled.** Monthly GMV has been flat since Nov-2017, and Jun–Aug 2018 averaged "
        f"{brl(pl['avg_monthly_gmv_jun_aug_2018'])}/month, **{pct(-pl['jun_aug_vs_mar_may'])} below Mar–May**. The headline "
        f"\"+{pct(st['yoy_ytd'], 0)} YoY\" is a base effect from the 2017 ramp-up. Supply kept growing: active sellers rose "
        f"{tr['sellers_from']:,.0f} → {tr['sellers_to']:,.0f} while GMV per seller fell {brl(tr['gmv_per_seller_from'])} → "
        f"{brl(tr['gmv_per_seller_to'])}/month. Demand is the constraint; {pct(st['repeat_rate_distinct_days'])} of buyers ever return.",
        f"- **The \"late delivery costs ~1.9 stars\" number is mostly a survey artefact.** The survey fires about 2 days "
        f"after the promised date, so most late orders are rated before the parcel arrives. For the same seller in the "
        f"same month, a late order records **{b['recorded_all_reviews']:+.2f}★** overall but **{b['post_delivery_reviews']:+.2f}★** "
        f"after delivery (carrier-leg only {st['carrier_leg_post_delivery']:+.2f}★; May-2018 strike natural experiment "
        f"{st['strike_iv_post_delivery']['estimate']:+.2f}★, CI {st['strike_iv_post_delivery']['ci95'][0]:+.1f} to "
        f"{st['strike_iv_post_delivery']['ci95'][1]:+.1f}).",
        f"- **The spring-2018 delivery slump had two causes.** Late rate Jan → Mar 2018: Olist cut the median promise by 4 days "
        f"({sh['promise']:+.1f} pp), carrier transit slowed ({sh['transit']:+.1f} pp), and seller handling was not the cause "
        f"({sh['seller_days']:+.1f} pp); no single state, category or lane.",
        f"- **Repurchase effects can't be measured here.** Late delivery shifts 180-day repurchase by {st['repurchase']['effect_pp']:+.2f} pp, "
        f"but the test can only detect ≥ {st['repurchase']['mde_pp']:.2f} pp ({pct(st['repurchase']['mde_rel'], 0)} of the base): "
        "underpowered, not 'no effect'.",
        "",
        "## Decisions (in priority order)",
        "| # | Decision | Why | Sized impact (12 mo) | Confidence | Owner / date |",
        "|---|---|---|---|---|---|",
    ]
    for x in rec:
        lines.append(f"| {x['id']} | **{x['title']}** | {x['why']} | {x['impact']} | {x['confidence']} | {x['owner']}; {x['date']} |")
    n1 = net["one_two_star_per_year"]
    lines += [
        "",
        f"**Net (the recommendations interact):** 1–2★/yr: #1 ≤ {n1['rec1_upper_bound']:,.0f}, #3 ≤ {n1['rec3_upper_bound']:,.0f}; "
        f"a full #2 rollout {n1['rec2_rollout_survey_today']:+,.0f} today vs {n1['rec2_rollout_after_rec1']:+,.0f} after #1. "
        "Upper bounds, not additive.",
        "",
        f"**Ask today:** approve #1 and the #2 A/B test: 4 weeks, 50/50 by customer, ≈{ab['orders_per_arm']:,.0f} orders/arm. "
        f"Primary metric: conversion. Guardrails: late ≤ 7% (MDE {ab['guardrail_mde_late_rate_pp']:.1f} pp), 1–2★ share. "
        "Kill rule: treatment late rate +3 pp for 7 days, or 1–2★ share +1 pp.",
        "",
        "**Deprioritised:** lane/carrier programme, seller-rating money (appendix).",
        "",
        "---",
        "### Appendix: methodology and caveats",
        *[f"- {x}" for x in r["demoted"]],
        f"- Interactions: {net['interactions']}",
        "- All KPIs come from the governed metrics layer (metrics/metrics.yml). The window is stated with every number.",
        "- Review effects are reported two ways: all reviews (what the platform records) and post-delivery reviews only. "
        "The post-delivery subsample is selected (angry customers answer early), so it is a bound, not the effect. "
        "The same-delivery-time design conditions on a mediator and is descriptive only. The regression discontinuity "
        "at the promise date fails (bunching, and a survey-timing switch at the same cutoff) and is shown only as a "
        "falsification exhibit.",
        "- Promise policies were evaluated on a rolling backtest with no look-ahead: seller and lane history use only "
        "earlier deliveries. Never-delivered orders count as late. The policy was chosen on Oct-2017..Mar-2018 and "
        "reported on Apr..Aug-2018. The conversion upside is NOT measured: Fisher, Gallino & Xu (2019) measured actual "
        "delivery speed (+1.45% sales per business day), not a displayed promise, so the memo gives break-even "
        "elasticities.",
        "- The text labels come from a keyword classifier checked against single-annotator labels (author "
        "verification pending). Shares are corrected for misclassification with bootstrap CIs.",
        "- The extract is described by Olist as \"100k orders\" and may not be the full marketplace. Nov-2016 is "
        "missing and capture stops on 2018-08-29.",
        "- Not in the data: costs, margins, refunds, sessions/conversion, carrier IDs, Olist's targets.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    r = build()
    (REPORTS / "recommendations.json").write_text(json.dumps(r, indent=2, default=str))
    (DOCS / "exec_memo.md").write_text(render(r))
    print(render(r)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
