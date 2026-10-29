"""Generate docs/RESULTS.md: every headline number with the report file + field it comes from.

README / memo quote these numbers; regenerate with `make results`.
Run: python -m marketplace.results
"""

from __future__ import annotations

import sys

from marketplace.analysis.common import read_report
from marketplace.metrics import MetricsLayer
from marketplace.paths import DOCS


def pct(v, d=1):
    return f"{100 * v:.{d}f}%"


def brl(v):
    return f"R${v:,.0f}"


def main() -> int:
    ml = MetricsLayer.load()
    g = read_report("growth")
    c = read_report("cohorts")
    di = read_report("delivery_impact")
    pp = read_report("promise_policy")
    s = read_report("sellers")
    ln = read_report("lanes")
    an = read_report("anomalies")
    rc = read_report("root_cause")
    mc = read_report("metric_conflicts")
    voc = read_report("voc") if (DOCS.parent / "reports" / "voc.json").exists() else None
    ytd = g["ytd_jan_aug_2018_vs_2017"]
    rv = di["review"]
    rec = pp["policies"][pp["recommended_policy"]]
    cur = pp["policies"]["current_olist_estimate"]
    t2 = next(t for t in s["tiers"] if t["tier"].startswith("T2"))
    worst = ln["worst_lanes"][0]
    rd5 = next(r for r in di["rd"]["local_linear"] if r["bandwidth_days"] == 5)
    feb = next(m for m in rc["moves"] if m["kpi"] == "on_time_delivery_rate")
    feb_d = feb["by_dimension"][feb["dimension_ranking_by_surprise"][0]]
    rows = [
        ("Business scale", "GMV, all time (governed)", brl(ml.value("gmv")), "metrics layer `gmv`"),
        ("", "Revenue orders", f"{ml.value('orders'):,.0f}", "metrics layer `orders`"),
        ("", "AOV", brl(ml.value("aov")), "metrics layer `aov`"),
        ("", "On-time delivery rate", pct(ml.value("on_time_delivery_rate")), "metrics layer"),
        ("", "Avg review score", f"{ml.value('avg_review_score'):.2f}", "metrics layer"),
        ("", "NPS-style score", f"{ml.value('nps_style_score'):.1f}", "metrics layer"),
        ("", "Cancellation rate", pct(ml.value("cancellation_rate"), 2), "metrics layer"),
        ("", "Freight / item price", pct(ml.value("freight_to_price_ratio")), "metrics layer"),
        ("Growth (a)", "GMV Jan-Aug 2018 vs Jan-Aug 2017", f"{pct(ytd['pct_change'])}", "growth.json ytd_jan_aug_2018_vs_2017"),
        ("", "...explained by more customers", f"{pct(ytd['drivers']['active_customers']['contribution_brl'] / ytd['delta_gmv'])} of the BRL increase (customers {pct(ytd['drivers']['active_customers']['pct_change'])}, orders/customer {pct(ytd['drivers']['orders_per_customer']['pct_change'])}, AOV {pct(ytd['drivers']['aov']['pct_change'])})", "growth.json drivers"),
        ("", "Decomposition residual", f"{ytd['log_residual']:.1e}", "growth.json log_residual"),
        ("Retention (b)", "People with 2+ orders (lifetime)", pct(c["lifetime_repeat_rate"], 2), "cohorts.json lifetime_repeat_rate"),
        ("", "2nd order on a later day within 365 d (Kaplan-Meier)", pct(c["km_cumulative_2nd_order_later_day"]["365"], 2), "cohorts.json"),
        ("", "Repeat orders' share of GMV", pct(c["repeat_gmv_share"], 2), "cohorts.json"),
        ("", "Next orders that are same-day split baskets", pct(c["share_of_next_orders_same_day"]), "cohorts.json"),
        ("Delivery -> outcome (c, H6)", "Review: late vs on-time, naive", f"{rv['naive']['diff']:+.2f} stars", "delivery_impact.json review.naive"),
        ("", "Review: FE (seller, category, state, month)", f"{rv['B_fe_controls']['estimate']:+.2f} [{rv['B_fe_controls']['ci95'][0]:.2f}, {rv['B_fe_controls']['ci95'][1]:.2f}]", "review.B_fe_controls"),
        ("", "Review: within seller x month", f"{rv['C_within_seller_month']['estimate']:+.2f} [{rv['C_within_seller_month']['ci95'][0]:.2f}, {rv['C_within_seller_month']['ci95'][1]:.2f}]", "review.C_within_seller_month"),
        ("", "Review: same delivery time, promise broken", f"{rv['D_same_delivery_time']['estimate']:+.2f} [{rv['D_same_delivery_time']['ci95'][0]:.2f}, {rv['D_same_delivery_time']['ci95'][1]:.2f}]", "review.D_same_delivery_time"),
        ("", "1-2 star share: late vs on-time (FE)", f"{100 * rv['B_fe_controls_low_review']['estimate']:+.1f} pp", "review.B_fe_controls_low_review"),
        ("", "RD jump at the promised date (+-5 d)", f"{rd5['estimate']:+.2f} [{rd5['ci95'][0]:.2f}, {rd5['ci95'][1]:.2f}]", "rd.local_linear"),
        ("", "RD density ratio 0->+1 vs -1->0", f"{di['rd']['density_ratio_plus1_over_0']:.2f} vs {di['rd']['density_ratio_0_over_minus1']:.2f}", "rd density ratios"),
        ("", "180-d repurchase: base rate", pct(di["repurchase"]["base_rate"], 2), "repurchase.base_rate"),
        ("", "180-d repurchase: late effect (FE LPM)", f"{100 * di['repurchase']['fe_lpm']['estimate']:+.2f} pp [{100 * di['repurchase']['fe_lpm']['ci95'][0]:.2f}, {100 * di['repurchase']['fe_lpm']['ci95'][1]:+.2f}]", "repurchase.fe_lpm"),
        ("", "Repeat GMV lost to late deliveries, 12 mo", f"{brl(di['impact']['lost_repeat_gmv_brl_point'])} (95% CI {brl(di['impact']['lost_repeat_gmv_brl_ci95'][0])} to {brl(di['impact']['lost_repeat_gmv_brl_ci95'][1])})", "impact"),
        ("", "Extra 1-2 star reviews from late deliveries, 12 mo", f"{di['impact']['extra_1_2_star_reviews_point']:,.0f}", "impact"),
        ("Promise (H1-H3)", "Median padding (promised - actual)", f"{pp['padding']['overall_quantiles']['p50']:.0f} days; {pct(pp['padding']['share_padded_over_7_days'])} of orders > 7 days early", "promise_policy.json padding"),
        ("", "Quantile model P80 / P90 coverage (test Apr-Aug 2018)", f"{pct(pp['model_eval']['p80']['model_coverage'])} / {pct(pp['model_eval']['p90']['model_coverage'])}", "model_eval"),
        ("", "Pinball loss P90: model vs lane baseline vs Olist estimate", f"{pp['model_eval']['p90']['model_pinball']:.2f} vs {pp['model_eval']['p90']['lane_baseline_pinball']:.2f} vs {pp['model_eval']['p90']['olist_estimate_pinball']:.2f}", "model_eval"),
        ("", "Recommended policy", pp["recommended_policy"], "recommended_policy"),
        ("", "...promise days saved / late rate", f"{rec['mean_days_saved_vs_current']:.1f} d; {pct(cur['late_rate'])} -> {pct(rec['late_rate'])}", "policies"),
        ("", "...expected review change / 1-2 star share", f"{rec['expected_delta_avg_review']:+.3f} stars; {rec['expected_delta_1_2_star_share_pp']:+.2f} pp", "policies"),
        ("", "...repurchase GMV at risk / yr", brl(rec["repurchase_gmv_at_risk_brl_per_year"]), "policies"),
        ("", "...conversion upside / yr at 0.25-1.0% per day (assumed)", f"{brl(rec['conversion_benefit_brl_per_year_sensitivity']['0.25%_per_day'])} - {brl(rec['conversion_benefit_brl_per_year_sensitivity']['1.00%_per_day'])}", "policies"),
        ("Sellers (d)", "Top-10% sellers' GMV share (12 mo)", pct(s["pareto"]["top_10pct_sellers_share"]), "sellers.json pareto"),
        ("", "Sellers needed for 80% of GMV", pct(s["pareto"]["share_of_sellers_for_80pct_gmv"]), "sellers.json pareto"),
        ("", "Seller HHI (12 mo)", f"{s['hhi_window']:.0f}", "sellers.json"),
        ("", "Fix-first tier (top-10% GMV, below quality bar)", f"{t2['sellers']} sellers, {pct(t2['gmv_share'])} of GMV, on-time {pct(t2['on_time'])}", "sellers.json tiers"),
        ("Lanes (e)", "Worst lane", f"{worst['lane']}: {worst['delivered_orders']:,} orders, late {pct(worst['late_rate'])}, {worst['excess_late_orders']:.0f} excess late orders", "lanes.json worst_lanes[0]"),
        ("", "Excess late orders in 10 worst lanes / all lanes", f"{ln['summary']['top10_excess_late_orders']:.0f} / {ln['summary']['excess_late_orders_total']:.0f}", "lanes.json summary"),
        ("", "1-2 star reviews avoidable (10 worst lanes)", f"{ln['summary']['low_reviews_avoidable_top10']:.0f}", "lanes.json summary"),
        ("Monitoring (f)", "Online alerts / needing a human", f"{an['n_online_alerts']} / {an['n_online_investigate']}", "anomalies.json"),
        ("", "Black Friday 2017", f"{an['black_friday_2017']['orders']:.0f} orders, {an['black_friday_2017']['multiple_of_expected_orders']:.1f}x expected, online z {an['black_friday_2017']['orders_z_online']:.1f}, classified {an['black_friday_2017']['classification']}", "anomalies.json"),
        ("Root cause (H4)", f"On-time {feb['from_month'][:7]} -> {feb['to_month'][:7]}", f"{pct(feb_d['kpi_from'])} -> {pct(feb_d['kpi_to'])}; rate effect {100 * feb_d['rate_effect']:+.1f} pp, mix {100 * feb_d['mix_effect']:+.2f} pp; {pct(feb_d['share_of_segments_improving'], 0)} of volume improved", "root_cause.json"),
        ("", "Simpson reversals (all / material)", f"{rc['simpson_scan']['n_simpson']} of {rc['simpson_scan']['n_cases']} / {rc['simpson_scan']['n_material_simpson']}", "root_cause.json simpson_scan"),
        ("Governance (H7)", "Repeat rate by customer_unique_id vs customer_id", f"{pct(mc['customer_identity']['repeat_rate']['governed_lifetime_share_of_people_with_2plus_orders'], 2)} vs {pct(mc['customer_identity']['repeat_rate']['rejected_customer_id_based'], 2)}", "metric_conflicts.json"),
        ("", "On-time Apr-2018: purchase-month vs delivery-month cohorting", f"{pct(mc['on_time_delivery']['largest_monthly_gaps_purchase_vs_delivery_month'][0]['purchase_cohort_on_time'])} vs {pct(mc['on_time_delivery']['largest_monthly_gaps_purchase_vs_delivery_month'][0]['delivery_month_on_time'])}", "metric_conflicts.json"),
        ("", "GMV: item price vs incl. freight (all time)", f"{brl(mc['gmv']['variants']['governed: item price, revenue orders']['total_brl'])} vs {brl(mc['gmv']['variants']['incl. freight']['total_brl'])}", "metric_conflicts.json"),
    ]
    if voc and voc.get("evaluation"):
        sh = voc["negative_review_reason_share_weighted"]
        top = sorted(sh.items(), key=lambda kv: -kv[1])[:4]
        ev = voc["evaluation"]
        b = ev["rules_gold_B_160_fresh_holdout"]
        llm = ev["llm_on_gold_items_it_labelled"]
        rows += [
            ("Voice of customer (H5)", "Reviews labelled by rules / gold A + B", f"{voc['population']['reviews_with_text']:,} / {ev['rules_gold_A_240_seen_before_rules']['n']} + {b['n']}", "voc.json"),
            ("", "Rules accuracy on fresh holdout B (95% CI) / macro-F1", f"{pct(b['accuracy'])} ({pct(b['accuracy_ci95'][0])}-{pct(b['accuracy_ci95'][1])}) / {b['macro_f1']:.2f}; majority baseline {pct(b['majority_class_baseline_accuracy'])}", "voc.json evaluation"),
            ("", "Rules accuracy on gold A (seen before rules)", pct(ev["rules_gold_A_240_seen_before_rules"]["accuracy"]), "voc.json evaluation"),
            ("", "LLM (qwen2.5:7b) accuracy on gold items reached", f"{pct(llm['accuracy'])} (n={llm['n']}); rule-LLM agreement {pct(voc['rule_vs_llm']['rule_llm_agreement'])} on {voc['rule_vs_llm']['n_reviews_with_both_labels']}", "voc.json"),
            ("", "Top reasons in 1-2 star reviews", "; ".join(f"{k} {pct(v)}" for k, v in top), "voc.json"),
            ("", "#1 reason on 1-2 star reviews of ON-TIME orders", "; ".join(f"{k} {pct(v)}" for k, v in sorted(voc["negative_on_time_review_reason_share"].items(), key=lambda kv: -kv[1])[:2]), "voc.json"),
            ("", "Incomplete-order complaints on multi-item orders vs base", f"{pct(voc['incomplete_order_reviews_on_multi_item_orders'])} vs {pct(voc['all_text_reviews_on_multi_item_orders'])}", "voc.json"),
            ("", "'late/not received' label rate: late vs on-time orders", f"{pct(voc['external_validity']['late_or_not_received_label_rate_when_order_late'])} vs {pct(voc['external_validity']['late_or_not_received_label_rate_when_on_time'])}", "voc.json external_validity"),
        ]
    lines = ["# Results (generated)", "",
             "_Generated by `make results` from reports/*.json and the metrics layer. "
             "Each row names its source._", "",
             "| Area | Metric | Value | Source |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {v} | `{src}` |" for a, b, v, src in rows]
    (DOCS / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
