"""Generate docs/RESULTS.md: every headline number with the report file + field it comes from.

README / memo / dashboard quote these numbers; regenerate with `make results`.
Run: python -m marketplace.results
"""

from __future__ import annotations

import sys

from marketplace.analysis.common import read_report
from marketplace.metrics import MetricsLayer
from marketplace.paths import DOCS

W0, W1 = "2017-01-01", "2018-08-31"


def pct(v, d=1):
    return "–" if v is None else f"{100 * v:.{d}f}%"


def brl(v):
    s = "−" if v < 0 else ""
    return f"{s}R${abs(v):,.0f}"


def ci(c, d=2):
    return f"[{c[0]:.{d}f}, {c[1]:.{d}f}]"


def main() -> int:
    ml = MetricsLayer.load()
    g, c, di = read_report("growth"), read_report("cohorts"), read_report("delivery_impact")
    pp, s, ln = read_report("promise_policy"), read_report("sellers"), read_report("lanes")
    an, mc = read_report("anomalies"), read_report("metric_conflicts")
    voc, rv, rec = read_report("voc"), read_report("review_value"), read_report("recommendations")
    sup, tree = g["supply_side"], g["supply_side"]["jun_aug_vs_mar_may_seller_tree"]
    b = di["bounds"]
    fy, sel, te = pp["policies"]["full_year"], pp["policies"]["selection"], pp["policies"]["test"]
    lever = di["impact"]["survey_on_delivery_lever"]
    iv = di["F_strike_iv"]
    stg = rec["state"]["stages_jan_mar_2018"]
    cov = pp["coverage"]
    ev = voc["evaluation"]["rules_vs_silver_B_160_fresh_holdout"]
    ot = voc["negative_on_time_share_corrected_for_misclassification"]
    rows = [
        ("Scale (window Jan-2017..Aug-2018)", "GMV / revenue orders",
         f"{brl(ml.value('gmv', start=W0, end=W1))} / {ml.value('orders', start=W0, end=W1):,.0f}", "metrics layer, windowed"),
        ("", "GMV / revenue orders, all time (incl. 2016 + Sep-Oct 2018 tail)",
         f"{brl(ml.value('gmv'))} / {ml.value('orders'):,.0f}", "metrics layer, unwindowed"),
        ("", "On-time / avg review (window)",
         f"{pct(ml.value('on_time_delivery_rate', start=W0, end=W1))} / {ml.value('avg_review_score', start=W0, end=W1):.2f}", "metrics layer"),
        ("Growth", "Jun-Aug 2018 vs Mar-May 2018 monthly GMV", pct(sup["plateau"]["jun_aug_vs_mar_may"]), "growth.json supply_side.plateau"),
        ("", "Active sellers / GMV per seller (Mar-May -> Jun-Aug avg)",
         f"{tree['sellers_from']:,.0f} -> {tree['sellers_to']:,.0f} / {brl(tree['gmv_per_seller_from'])} -> {brl(tree['gmv_per_seller_to'])}", "growth.json seller tree"),
        ("", "New sellers' share of 2018 GMV", pct(sup["new_seller_gmv_share_2018"]), "growth.json"),
        ("", "Funnel: MQL -> won -> sold; funnel sellers' share of 2018 GMV",
         f"{sup['funnel']['mqls']:,.0f} -> {sup['funnel']['won']:,.0f} -> {sup['funnel']['sold']:,.0f}; {pct(sup['funnel']['funnel_seller_share_of_2018_gmv'])}", "growth.json funnel"),
        ("", "Jan-Aug 2018 vs Jan-Aug 2017 GMV (ramp-up base effect)", pct(g["ytd_jan_aug_2018_vs_2017"]["pct_change"]), "growth.json"),
        ("Retention", "Repeat rate, governed (bought on >= 2 distinct days)", pct(ml.value("repeat_purchase_rate"), 2), "metrics layer"),
        ("", "2nd order on a later day within 180 d (KM)", pct(c["km_cumulative_2nd_order_later_day"]["180"], 2), "cohorts.json"),
        ("Survey timing", "Late orders reviewed before delivery", pct(di["survey_timing"]["late_answered_before_delivery_share"]), "delivery_impact.json survey_timing"),
        ("Late -> review (stars)", "Within seller x month: recorded / post-delivery",
         f"{b['C_within_seller_month']['recorded_all_reviews']:+.2f} / {b['C_within_seller_month']['post_delivery_reviews']:+.2f}", "delivery_impact.json bounds"),
        ("", "Same delivery time (descriptive, mediator): recorded / post-delivery",
         f"{b['D_same_delivery_time']['recorded_all_reviews']:+.2f} / {b['D_same_delivery_time']['post_delivery_reviews']:+.2f}", "bounds"),
        ("", "Carrier-leg only, post-delivery, within seller x month",
         f"{di['E_carrier_leg_only']['estimate']:+.2f} {ci(di['E_carrier_leg_only']['ci95'])}", "E_carrier_leg_only"),
        ("", "Truckers' strike IV: recorded / post-delivery (first-stage F)",
         f"{iv['recorded_all_reviews']['iv_late_effect']['estimate']:+.2f} {ci(iv['recorded_all_reviews']['iv_late_effect']['ci95'])} (F {iv['recorded_all_reviews']['first_stage_F']:.0f}) / "
         f"{iv['post_delivery_reviews']['iv_late_effect']['estimate']:+.2f} {ci(iv['post_delivery_reviews']['iv_late_effect']['ci95'])} (F {iv['post_delivery_reviews']['first_stage_F']:.0f})", "F_strike_iv"),
        ("", "Survey-on-delivery lever: 1-2 star reviews avoided / yr; network avg stars",
         f"<= {lever['one_two_star_reviews_avoided_upper_bound']:,.0f}; +{lever['network_avg_review_gain']:.2f}", "impact.survey_on_delivery_lever"),
        ("Repurchase", "180-d effect / MDE (80% power) / MDE relative to base",
         f"{100 * di['repurchase']['fe_lpm']['estimate']:+.2f} pp / {100 * di['repurchase']['mde_80pct_power']:.2f} pp / {pct(di['repurchase']['mde_relative_to_base'], 0)}", "repurchase"),
        ("Review value", "Seller next-4-week GMV per extra 1-2 star review",
         f"{brl(rv['brl_next4w_gmv_per_extra_bad_review']['estimate'])} {ci(rv['brl_next4w_gmv_per_extra_bad_review']['ci95'], 0)}, p={rv['brl_next4w_gmv_per_extra_bad_review']['p']:.2f}", "review_value.json"),
        ("Promise", "Median padding; share > 7 days early",
         f"{pp['padding']['overall_quantiles']['p50']:.0f} d; {pct(pp['padding']['share_padded_over_7_days'])}", "promise_policy.json padding"),
        ("", "Late rate today: selection Oct-Mar / test Apr-Aug / full year (never-delivered = late)",
         f"{pct(sel['current_olist_estimate']['late_rate'])} / {pct(te['current_olist_estimate']['late_rate'])} / {pct(fy['current_olist_estimate']['late_rate'])}", "policies"),
        ("", "Lane-P80: days saved / late rate (full year)",
         f"{fy['lane_q80']['mean_days_saved_vs_current']:.1f} d / {pct(fy['lane_q80']['late_rate'])}", "policies.full_year"),
        ("", "Lane-P80 break-even conversion lift per promise-day (survey today)",
         pct(fy["lane_q80"]["survey_today"]["breakeven_conversion_lift_per_promise_day"], 3), "policies.full_year"),
        ("", "Policy chosen by the pre-set rule on the selection period", pp["recommended_policy"], "recommended_policy"),
        ("", "Model P50/P80/P90 coverage (ceil), selection / test",
         " / ".join(f"{pct(cov['selection'][q]['model_coverage_ceil'])}-{pct(cov['test'][q]['model_coverage_ceil'])}" for q in ("p50", "p80", "p90")), "coverage"),
        ("", "P90 pinball (test): model / lane / Olist",
         f"{cov['test']['p90']['model_pinball_delivered']:.2f} / {cov['test']['p90']['lane_pinball_delivered']:.2f} / {cov['test']['p90']['olist_pinball_delivered']:.2f}", "coverage.test"),
        ("Root cause", "Jan->Mar 2018 late rate by stage: promise / transit / seller / unexplained (pp)",
         f"{stg['shapley_pp']['promise']:+.1f} / {stg['shapley_pp']['transit']:+.1f} / {stg['shapley_pp']['seller_days']:+.1f} / {stg['unexplained_pp_distribution_shape']:+.1f}", "root_cause.json stages"),
        ("", "In-flight monitor first alert, Feb-Mar 2018 slump (volume monitor: none)",
         an["inflight_late_monitor"]["first_alert_by_incident"]["feb_mar_2018_slowdown"], "anomalies.json inflight_late_monitor"),
        ("Lanes", "10 worst lanes excess late orders: lane-adjusted / vs network average",
         f"{ln['summary']['top10_excess_late_orders']:,.0f} / {ln['summary']['excess_vs_network_top10_old_method']:,.0f}", "lanes.json summary"),
        ("", "1-2 star avoidable in 10 worst lanes: recorded / post-delivery",
         f"{ln['summary']['low_reviews_avoidable_top10']:.0f} / {ln['summary']['low_reviews_avoidable_top10_post_delivery']:.0f}", "lanes.json summary"),
        ("Sellers", "Fix-first tier: sellers / GMV share / on-time",
         f"{next(t for t in s['tiers'] if t['tier'].startswith('T2'))['sellers']} / {pct(next(t for t in s['tiers'] if t['tier'].startswith('T2'))['gmv_share'])} / {pct(next(t for t in s['tiers'] if t['tier'].startswith('T2'))['on_time'])}", "sellers.json"),
        ("VoC", "Rules vs single-annotator labels, fresh set B (95% CI) / macro-F1",
         f"{pct(ev['accuracy'])} ({pct(ev['accuracy_ci95'][0])}-{pct(ev['accuracy_ci95'][1])}) / {ev['macro_f1']:.2f}", "voc.json evaluation"),
        ("", "On-time 1-2 star reasons, corrected: incomplete order / poor quality",
         f"{pct(ot['incomplete_order']['corrected'])} {ci([100 * x for x in ot['incomplete_order']['ci95']], 1)} / {pct(ot['poor_quality']['corrected'])} {ci([100 * x for x in ot['poor_quality']['ci95']], 1)}", "voc.json corrected"),
        ("Governance", "Apr-2018 on-time: purchase-month vs delivery-month cohort",
         f"{pct(mc['on_time_delivery']['largest_monthly_gaps_purchase_vs_delivery_month'][0]['purchase_cohort_on_time'])} vs {pct(mc['on_time_delivery']['largest_monthly_gaps_purchase_vs_delivery_month'][0]['delivery_month_on_time'])}", "metric_conflicts.json"),
        ("", "Repeat rate: distinct days vs counting same-day orders",
         f"{pct(mc['customer_identity']['repeat_rate']['governed_lifetime_share_bought_on_2plus_days'], 2)} vs {pct(mc['customer_identity']['repeat_rate']['rejected_counting_same_day_orders'], 2)}", "metric_conflicts.json"),
    ]
    lines = ["# Results (generated)", "",
             "_Generated by `make results` from reports/*.json and the metrics layer. Each row names its source; "
             "the window is stated where it matters._", "",
             "| Area | Metric | Value | Source |", "|---|---|---|---|"]
    lines += [f"| {a} | {m} | {v} | `{src}` |" for a, m, v, src in rows]
    (DOCS / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
