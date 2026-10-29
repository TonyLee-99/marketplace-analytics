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
    tree = sup["jun_jul_vs_mar_may_seller_tree"]
    lever = di["impact"]["survey_on_delivery_lever"]
    b = di["bounds"]["C_within_seller_month"]
    iv = di["F_strike_iv"]
    fy, sel = pp["policies"]["full_year"], pp["policies"]["selection"]
    q80, cap3, cap5 = fy["lane_q80"], fy["lane_q80_capped_3d"], sel["lane_q80_capped_5d"]
    cur = fy["current_olist_estimate"]
    an = pp["ab_analogs"]
    recal = pp["recalibrated_policy_summary"]
    stages = next(m for m in rc["moves"] if m["kpi"] == "on_time_delivery_rate"
                  and m["from_month"].startswith("2018-01") and m["to_month"].startswith("2018-03"))["stages"]
    rep = di["repurchase"]
    ot = voc["negative_on_time_share_corrected_for_misclassification"]
    inc_yr = voc["incomplete_order_1_2_star_reviews"] / voc["months_covered"] * 12
    t2 = next(t for t in s["tiers"] if t["tier"].startswith("T2"))
    # A/B: all lanes, 4 weeks of exposure, 50/50 by customer (volume from the test months)
    orders_4w = pp["coverage"]["test"]["n"] / 5 * 12 / 13
    p_late = an["2018-01"]["control_late"]
    n_arm = orders_4w / 2
    mde_late = 2.8 * math.sqrt(2 * p_late * (1 - p_late) / n_arm)
    recs = [
        {
            "id": 1,
            "title": "Split the survey: delivery-issue contact at promise + 2 days, star rating on confirmed delivery",
            "why": f"{pct(di['survey_timing']['late_answered_before_delivery_share'], 0)} of late orders are rated before they arrive.",
            "impact": f"removes ≤ {lever['one_two_star_reviews_avoided_upper_bound']:,.0f} pre-delivery 1–2★ ratings/yr "
            f"(≈{lever['one_two_star_avoided_exact_day_cells']:,.0f} with exact-day matching); value = rating accuracy, no BRL claimed",
            "confidence": "High on direction, medium on size",
            "owner": "CX product manager", "date": "ship by 2018-09-30",
        },
        {
            "id": 2,
            "title": "Don't roll out shorter promises; A/B a 3-day-capped lane-P80 after the peak",
            "why": f"Full year, lane-P80 saves {q80['mean_days_saved_vs_current']:.1f} d but late rises "
            f"{pct(cur['late_rate'])} → {pct(q80['late_rate'])}.",
            "impact": f"capped arm: −{cap3['mean_days_saved_vs_current']:.1f} d, late {pct(cur['late_rate'])} → "
            f"{pct(cap3['late_rate'])} (full year); pays only above +"
            f"{pct(cap3['survey_today']['breakeven_conversion_lift_per_promise_day'] or 0, 3)} conversion per day saved",
            "confidence": "Low: upside unmeasured",
            "owner": "Delivery-promise PM + analytics",
            "date": "run 2019-01-14 → 2019-02-10 (after the peak and after #1), final read-out 2019-03-03",
            "ab_design": {
                "unit": "customer (cookie), 50/50, all lanes; treatment promise = max(lane-P80, current − 3 days)",
                "primary_metric": "checkout conversion of sessions that saw a promise",
                "guardrail": "matured late rate, treatment − control ≤ +3 pp (read after promise + 7 days)",
                "guardrail_mde_pp": 100 * mde_late,
                "orders_per_arm": n_arm,
                "kill_metric": "in-flight past-promise share (real time): stop if treatment − control > 3 pp for 3 consecutive days",
                "analog_oct_2017": an["2017-10"],
                "analog_jan_2018": an["2018-01"],
                "overrides_preset_rule": f"The pre-set rule rejects every capped arm (5-day cap: {pct(cap5['late_rate'])} late in "
                f"Oct–Mar vs the 7% bar). Its own pick uses the 99th percentile in {recal['months_at_q99']} of "
                f"{recal['months']} months and lengthens promises by {recal['mean_extra_promise_days_full_year']:.1f} days on "
                "average all year. Testing a capped cut is a judgement call that overrides the rule.",
                "conversion_mde_note": "needs session counts (not in the extract): MDE ≈ 2.8·sqrt(2c(1−c)/S)",
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
            "confidence": "Medium (text classifier, silver labels)",
            "owner": "Marketplace ops + order-management engineering", "date": "scope by 2018-10-01",
        },
    ]
    demoted = [
        f"Seller quality plan for the {t2['sellers']} 'fix-first' sellers ({pct(t2['gmv_share'], 0)} of GMV, "
        f"{pct(t2['on_time'], 0)} on-time): ops hygiene, no measurable BRL.",
        f"Lane/carrier programme: against a lane-adjusted baseline the 10 worst lanes have only "
        f"{ln['summary']['top10_excess_late_orders']:,.0f} excess late orders/yr (≈{ln['summary']['low_reviews_avoidable_top10']:.0f} "
        f"1–2★ recorded, {ln['summary']['low_reviews_avoidable_top10_post_delivery']:.0f} post-delivery), down from "
        f"{ln['summary']['excess_vs_network_top10_old_method']:,.0f} vs the network average. No carrier ID exists.",
        f"Money on reviews: one extra 1–2★ review is associated with {brl(rv['brl_next4w_gmv_per_extra_bad_review']['estimate'])} "
        f"of the seller's next-4-week GMV (95% CI {brl(rv['brl_next4w_gmv_per_extra_bad_review']['ci95'][0])} to "
        f"{brl(rv['brl_next4w_gmv_per_extra_bad_review']['ci95'][1])}): not detectable. Caveat: per the dataset description, "
        "Olist sells through the 'Olist Store' on partner marketplaces, so buyers may mostly see the store's reputation "
        "rather than a seller's; the seller-week panel may be the wrong unit, so the null is uninformative.",
    ]
    net = {
        "one_two_star_per_year": {"rec1_upper_bound": -lever["one_two_star_reviews_avoided_upper_bound"],
                                  "rec1_exact_day": -lever["one_two_star_avoided_exact_day_cells"],
                                  "rec2_capped_rollout_survey_today": cap3["survey_today"]["extra_1_2_star_reviews_per_year"],
                                  "rec2_capped_rollout_after_rec1": cap3["survey_on_delivery"]["extra_1_2_star_reviews_per_year"],
                                  "rec3_upper_bound": -inc_yr},
        "interactions": "Rec 1 changes how lateness is recorded in stars, so the A/B runs after it ships, never across it. "
        "Rec 3 delays the recorded delivery, which delays the star survey and raises the measured late rate. "
        "Sizes are upper bounds and not additive.",
    }
    state = {
        "gmv_window": ml.value("gmv", start=W0, end=W1),
        "orders_window": ml.value("orders", start=W0, end=W1),
        "plateau": sup["plateau"],
        "seller_tree_full_months": tree,
        "yoy_ytd": g["ytd_jan_aug_2018_vs_2017"]["pct_change"],
        "repeat_rate_distinct_days": ml.value("repeat_purchase_rate"),
        "late_effect_bounds_within_seller_month": b,
        "carrier_leg_post_delivery": di["E_carrier_leg_only"]["estimate"],
        "strike_iv_recorded": iv["recorded_all_reviews"]["iv_late_effect"],
        "strike_iv_recorded_seller_fe": iv["recorded_robustness"]["iv_with_seller_fe"],
        "strike_ar_set": iv["recorded_robustness"]["anderson_rubin_95_set_day_clustered"],
        "strike_first_stage_F_day": iv["recorded_robustness"]["first_stage_F_day_clustered"],
        "repurchase": {"effect_pp": 100 * rep["fe_lpm"]["estimate"], "mde_pp": 100 * rep["mde_80pct_power"],
                       "mde_rel": rep["mde_relative_to_base"], "base": rep["base_rate"]},
        "stages_jan_mar_2018": stages,
    }
    return {"window": [W0, W1], "state": state, "recommendations": recs, "demoted": demoted, "net": net}


def render(r: dict) -> str:
    st, rec, net = r["state"], r["recommendations"], r["net"]
    pl, tr = st["plateau"], st["seller_tree_full_months"]
    b = st["late_effect_bounds_within_seller_month"]
    sh = st["stages_jan_mar_2018"]
    ab = rec[1]["ab_design"]
    a10 = ab["analog_oct_2017"]
    lines = [
        "# Marketplace: state of the business and three decisions",
        "",
        f"**To:** VP Marketplace · **Data:** Olist public extract, orders {r['window'][0]} to {r['window'][1]} · "
        "**Read time:** 5 min · _Generated by `make results`; every number is in docs/RESULTS.md_",
        "",
        "## State of the business",
        f"- **Growth has stalled.** GMV has been flat since Nov-2017. Jun–Jul 2018 ran **{pct(-pl['jun_jul_vs_mar_may_full_months'])} "
        f"below Mar–May** (days 1–20 of Jun–Aug: {pct(-pl['days_1_20_jun_aug_vs_mar_may'])}; August capture decays after "
        f"Aug 21; the World Cup overlaps Jun–Jul). Active sellers {tr['sellers_from']:,.0f} → {tr['sellers_to']:,.0f}, GMV per "
        f"seller {brl(tr['gmv_per_seller_from'])} → {brl(tr['gmv_per_seller_to'])}/month: demand is the constraint. "
        f"\"+{pct(st['yoy_ytd'], 0)} YoY\" is a ramp-up base effect.",
        f"- **\"Late costs ~1.9 stars\" is mostly survey timing.** The survey fires 2 days after the promised date, "
        f"so most late orders are rated before arrival. Same seller, same month: **{b['recorded_all_reviews']:+.2f}★** "
        f"recorded vs **{b['post_delivery_reviews']:+.2f}★** after delivery (carrier-leg only "
        f"{st['carrier_leg_post_delivery']:+.2f}★). A truckers'-strike IV confirms the recorded penalty "
        f"({st['strike_iv_recorded']['estimate']:+.2f}★; {st['strike_iv_recorded_seller_fe']['estimate']:+.2f} with seller FE).",
        f"- **The spring-2018 slump was a carrier-transit tail plus a promise cut.** Late rate Jan → Mar "
        f"{pct(sh['late_rate_from'])} → {pct(sh['late_rate_to'])}: carrier transit {sh['shapley_pp']['transit']:+.1f} pp, "
        f"promise cut {sh['shapley_pp']['promise']:+.1f} pp, sellers {sh['shapley_pp']['seller_days']:+.1f} pp.",
        f"- **Repurchase is underpowered:** {st['repurchase']['effect_pp']:+.2f} pp; MDE {st['repurchase']['mde_pp']:.2f} pp "
        f"({pct(st['repurchase']['mde_rel'], 0)} of base).",
        "",
        "## Decisions (in priority order)",
        "| # | Decision | Why | Sized impact (12 mo) | Confidence | Owner / date |",
        "|---|---|---|---|---|---|",
    ]
    for x in rec:
        lines.append(f"| {x['id']} | **{x['title']}** | {x['why']} | {x['impact']} | {x['confidence']} | {x['owner']}; {x['date']} |")
    lines += [
        "",
        f"**A/B (#2):** 50/50 by customer, ≈{ab['orders_per_arm']:,.0f} orders/arm. Primary: conversion. Guardrail: "
        f"matured late rate vs control ≤ +3 pp (MDE {ab['guardrail_mde_pp']:.1f} pp). Kill: in-flight past-promise share "
        f"+3 pp for 3 days. Oct-2017 analog: a 5-day cap was {a10['capped5_minus_control_pp']:+.1f} pp (would trip), the "
        f"3-day cap {a10['capped3_minus_control_pp']:+.1f} pp. This overrides the pre-set rule (appendix).",
        "",
        "**Ask today:** approve #1 and schedule #2. **Deprioritised:** lanes, seller-rating money (appendix).",
        "",
        "---",
        "### Appendix: methodology and caveats",
        *[f"- {x}" for x in r["demoted"]],
        f"- #2 and the pre-set rule: {ab['overrides_preset_rule']}",
        f"- Interactions: {net['interactions']}",
        "- #1 bound: pre-delivery ratings get the score of same-bin post-delivery ratings; "
        "61% of them sit in the 8+-day bins, where only 65 post-delivery reviews exist.",
        f"- Stage split: each stage's whole distribution is swapped (rank-preserving quantile mapping), Shapley over "
        f"orderings; residual {sh['residual_pp_dependence']:+.1f} pp.",
        f"- Strike IV: first-stage F {st['strike_first_stage_F_day']:.0f} (purchase-day clusters), Anderson–Rubin set "
        f"{st['strike_ar_set']}. The post-delivery IV is INVALID (the strike shifts who answers after delivery).",
        "- Review effects are bounds (post-delivery reviewers are selected); same-delivery-time conditions on a mediator; "
        "the RD at the promise fails and is shown only as a falsification exhibit.",
        "- Promise policies: rolling backtest, no look-ahead, never-delivered = late, chosen on Oct-2017..Mar-2018. "
        "Conversion upside is NOT measured; Fisher, Gallino & Xu (2019) measured actual delivery speed.",
        "- Text labels: keyword classifier vs single-annotator labels, "
        "misclassification-corrected.",
        "- Not in the data: costs, margins, refunds, sessions, carrier IDs, Olist's targets. The extract may be a sample.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    r = build()
    (REPORTS / "recommendations.json").write_text(json.dumps(r, indent=2, default=str))
    (DOCS / "exec_memo.md").write_text(render(r))
    print(render(r)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
