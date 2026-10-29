/* Marketplace executive dashboard. Data: window.DATA (built by marketplace.dashboard.build).
   No KPI formula lives here: ratio KPIs = sum(num)/sum(den) of governed components;
   derived KPIs evaluate the formula string from metrics.yml. Decisions come from
   reports/recommendations.json, the same file the memo is generated from. */
(function () {
  "use strict";
  const D = window.DATA, R = D.reports, C = D.cube;
  const css = (v) => getComputedStyle(document.body).getPropertyValue(v).trim();
  const COL = { s1: css("--series-1"), s2: css("--series-2"), s3: css("--series-3"), s4: css("--series-4"),
                good: css("--good"), bad: css("--critical"), muted: css("--text-muted"), grid: css("--grid"),
                neutral: css("--neutral"), text: css("--text-primary"), text2: css("--text-secondary") };

  // ---------- formatting & display names
  const fmtBRL = (v) => { if (v == null) return "–"; const s = v < 0 ? "−" : ""; v = Math.abs(v);
    return s + (v >= 1e6 ? "R$" + (v / 1e6).toFixed(2) + "M" : v >= 1e3 ? "R$" + (v / 1e3).toFixed(1) + "k" : "R$" + v.toFixed(0)); };
  const fmtN = (v) => v == null ? "–" : Math.round(v).toLocaleString("en-US");
  const fmtPct = (v, d = 1) => v == null ? "–" : (100 * v).toFixed(d) + "%";
  const fmtPP = (v, d = 1) => (v >= 0 ? "+" : "−") + Math.abs(100 * v).toFixed(d) + " pp";
  const sgn = (v, d = 2) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d);
  const TIERS = { T1: "Champions", T2: "Fix-first (large, below quality bar)", T3: "Grow (quality OK)", T4: "Watch (below bar)", T5: "Long tail (<20 orders)" };
  const nice = (s) => {
    if (s == null) return "–";
    s = String(s);
    if (/^[A-Z]{2}>[A-Z]{2}$/.test(s)) return s.replace(">", "→");
    if (/^T\d /.test(s)) return TIERS[s.slice(0, 2)] || s;
    const map = { A_top10pct: "Top-10% sellers", B_next40pct: "Next-40% sellers", C_bottom50pct: "Bottom-50% sellers",
                  new_seller: "New sellers", seller_late_handover: "Seller handed over late", seller_on_time_handover: "Seller on time (carrier leg)",
                  not_handed_over: "Not handed over", customer_state: "Customer state", seller_state: "Seller state",
                  lane_top: "Lane", fulfilment_leg: "Fulfilment leg", seller_tier: "Seller tier", category: "Category" };
    if (map[s]) return map[s];
    return s.replace(/_/g, " ").replace(/\b\w/, (c) => c.toUpperCase());
  };
  const fmt = (name, v) => {
    const u = (D.meta[name] || {}).unit;
    if (u === "BRL") return fmtBRL(v);
    if (u === "ratio") return fmtPct(v);
    if (u === "count") return fmtN(v);
    if (u === "days") return v == null ? "–" : v.toFixed(1) + " d";
    return v == null ? "–" : v.toFixed(2);
  };
  const base = (extra = {}) => Object.assign({
    margin: { l: 56, r: 16, t: 8, b: 44 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "-apple-system, Segoe UI, Helvetica, Arial, sans-serif", size: 12, color: COL.text2 },
    xaxis: { gridcolor: COL.grid, zeroline: false, linecolor: COL.grid, automargin: true },
    yaxis: { gridcolor: COL.grid, zeroline: false, automargin: true },
    hovermode: "closest", hoverlabel: { bgcolor: "#fff", bordercolor: COL.grid, font: { color: COL.text } },
    showlegend: false, legend: { orientation: "h", y: 1.12, x: 0 },
  }, extra);
  const ax = (title, extra = {}) => Object.assign({ gridcolor: COL.grid, zeroline: false, title: { text: title, font: { size: 11 } }, automargin: true }, extra);
  const cfg = { displayModeBar: false, responsive: true };
  const plot = (id, traces, layout) => Plotly.react(id, traces, base(layout), cfg);

  // ---------- filters / cube aggregation
  const M = C.months;
  const st = { from: Math.max(0, M.indexOf("2018-01")), to: M.length - 1, state: "ALL", cat: "ALL" };
  function aggregate(fromIdx, toIdx, byMonth) {
    const si = st.state === "ALL" ? -1 : C.states.indexOf(st.state);
    const ci = st.cat === "ALL" ? -1 : C.categories.indexOf(st.cat);
    const acc = {};
    for (let i = 0; i < C.m.length; i++) {
      const m = C.m[i];
      if (m < fromIdx || m > toIdx) continue;
      if (si >= 0 && C.s[i] !== si) continue;
      if (ci >= 0 && C.c[i] !== ci) continue;
      const key = byMonth ? m : 0, k = C.metrics[C.k[i]];
      acc[key] = acc[key] || {};
      const a = (acc[key][k] = acc[key][k] || { num: 0, den: 0, hasDen: false });
      a.num += C.num[i];
      if (C.den[i] != null) { a.den += C.den[i]; a.hasDen = true; }
    }
    const out = {};
    for (const key of Object.keys(acc)) {
      const vals = {};
      for (const k of C.metrics) { const a = acc[key][k]; vals[k] = !a ? null : a.hasDen ? (a.den ? a.num / a.den : null) : a.num; }
      for (const [d, f] of Object.entries(D.derived)) {
        try { vals[d] = Function(...Object.keys(vals), "return " + f)(...Object.values(vals)); } catch (e) { vals[d] = null; }
      }
      out[key] = vals;
    }
    return byMonth ? out : out[0] || {};
  }

  // ---------- pages
  const PAGES = [["exec", "Executive"], ["growth", "Growth"], ["customers", "Customers"],
                 ["delivery", "Delivery & Promise"], ["sellers", "Sellers & Voice of Customer"], ["rca", "Why did it move?"]];
  const main = document.getElementById("main"), nav = document.getElementById("nav");
  PAGES.forEach(([id, label]) => {
    const b = document.createElement("button"); b.textContent = label; b.dataset.page = id;
    b.onclick = () => { location.hash = id; }; nav.appendChild(b);
    const p = document.createElement("section"); p.className = "page"; p.id = "page-" + id; main.appendChild(p);
  });
  const card = (id, cap, cls = "chart", badge = false) =>
    `<div class="card"><h2 id="t-${id}"></h2>${badge ? '<span class="badge">filters</span>' : ""}<p class="cap">${cap}</p><div id="${id}" class="${cls}"></div></div>`;
  const setT = (id, t) => { document.getElementById("t-" + id).textContent = t; };

  // ===== EXECUTIVE
  const KPI4 = ["gmv", "orders", "on_time_delivery_rate", "avg_review_score"];
  document.getElementById("page-exec").innerHTML =
    `<div class="grid g4" id="kpis"></div><div style="height:14px"></div>
     <div class="grid g2">${card("c-gmv", "Governed GMV: item price, non-canceled orders, by purchase month.", "chart", true)}
     ${card("c-hero", "Mean review score of delivered orders, Jan-2017–Aug-2018, by whether the review was answered before or after the parcel arrived. The survey is sent ~2 days after the promised date.")}</div>
     <div style="height:14px"></div><div class="grid g2">
     <div class="card"><h2>Three decisions: one survey change, one test, one fix</h2><p class="cap">Same source as docs/exec_memo.md (reports/recommendations.json). Sizes are upper bounds; the recommendations interact.</p><div id="exec-recs"></div></div>
     ${card("c-stage", "Change in late rate Jan → Mar 2018 by process stage (Shapley split of median shifts); the remainder is distribution shape.")}</div>`;

  function renderExec() {
    const sel = aggregate(st.from, st.to, false);
    const monthly = aggregate(0, M.length - 1, true);
    const yf = st.from - 12, yt = st.to - 12;
    const prior = yf >= 0 ? aggregate(yf, yt, false) : null;
    const win = `${M[st.from]}–${M[st.to]}`;
    document.getElementById("kpis").innerHTML = KPI4.map((k) => {
      const v = sel[k], m = D.meta[k];
      let d = "<span class='muted'>no year-earlier data in range</span>";
      if (prior && prior[k] != null && v != null) {
        const txt = m.unit === "ratio" ? fmtPP(v - prior[k]) : m.unit === "score" ? sgn(v - prior[k]) + "★"
          : ((v / prior[k] - 1) >= 0 ? "+" : "−") + Math.abs(100 * (v / prior[k] - 1)).toFixed(0) + "%";
        d = `<span class="pill flat">${txt} YoY (vs ${M[yf]}–${M[yt]})</span>`;
      }
      return `<div class="card kpi" title="${m.definition.replace(/"/g, "'")}"><div class="name">${m.label.replace(" (BRL)", "").replace(" (1-5)", "")}, ${win}</div>
              <div class="val">${fmt(k, v)}</div><div class="row">${d}</div></div>`;
    }).join("");
    const months = M.slice(st.from, st.to + 1), g = months.map((_, i) => (monthly[st.from + i] || {}).gmv);
    const pl = R.growth.supply_side.plateau;
    setT("c-gmv", st.state === "ALL" && st.cat === "ALL"
      ? `GMV has been flat since Nov-2017; Jun–Aug 2018 is ${fmtPct(-pl.jun_aug_vs_mar_may)} below Mar–May`
      : `GMV by month for the selected slice (${win})`);
    plot("c-gmv", [{ type: "bar", x: months, y: g, marker: { color: COL.s1 }, hovertemplate: "%{x}<br>GMV R$%{y:,.0f}<extra></extra>" }],
      { yaxis: ax("GMV per month (BRL)", { tickprefix: "R$", tickformat: "~s" }), xaxis: ax("purchase month") });
  }
  function renderExecStatic() {
    const S = R.delivery_impact.survey_timing.score_by_late_and_timing;
    const get = (late, before) => S.find((r) => r.is_late === late && r.is_review_before_delivery === before);
    const cats = ["On time", "Late"];
    const after = [get(false, false), get(true, false)], before = [get(false, true), get(true, true)];
    setT("c-hero", `Late orders rated after they arrive score ${after[1].mean.toFixed(1)}★; rated before they arrive, ${before[1].mean.toFixed(1)}★`);
    plot("c-hero", [
      { type: "bar", name: "reviewed after delivery", x: cats, y: after.map((r) => r.mean), marker: { color: COL.s1 }, customdata: after.map((r) => r.size), hovertemplate: "%{x}, after delivery: %{y:.2f}★ (n=%{customdata:,})<extra></extra>" },
      { type: "bar", name: "reviewed before delivery", x: cats, y: before.map((r) => r.mean), marker: { color: COL.s2 }, customdata: before.map((r) => r.size), hovertemplate: "%{x}, before delivery: %{y:.2f}★ (n=%{customdata:,})<extra></extra>" },
    ], { barmode: "group", showlegend: true, yaxis: ax("mean review score (1–5)", { range: [0, 5] }), xaxis: ax("delivery vs promise") });
    const rec = R.recommendations.recommendations;
    document.getElementById("exec-recs").innerHTML = "<ol style='margin:0;padding-left:18px;line-height:1.45'>" +
      rec.map((r) => `<li><b>${r.title}.</b> ${r.impact}. <span class="muted">Confidence: ${r.confidence}. ${r.owner}, ${r.date}.</span></li>`).join("") + "</ol>";
    const sh = R.recommendations.state.stages_jan_mar_2018;
    const labs = { promise: "Promise cut (4 days)", transit: "Carrier transit slower", seller_days: "Seller handling" };
    const ks = Object.keys(sh.shapley_pp);
    setT("c-stage", `Spring-2018 slump: shorter promises (${sgn(sh.shapley_pp.promise, 1)} pp) and slower carriers (${sgn(sh.shapley_pp.transit, 1)} pp), not sellers`);
    plot("c-stage", [{ type: "bar", orientation: "h", y: ks.map((k) => labs[k]).concat(["Distribution shape (unexplained)"]),
      x: ks.map((k) => sh.shapley_pp[k]).concat([sh.unexplained_pp_distribution_shape]),
      marker: { color: ks.map((k) => (sh.shapley_pp[k] >= 0 ? COL.s2 : COL.s1)).concat([COL.neutral]) },
      hovertemplate: "%{y}: %{x:+.1f} pp<extra></extra>" }],
      { margin: { l: 200, r: 16, t: 8, b: 44 }, xaxis: ax(`pp of late rate (${fmtPct(sh.late_rate_from)} → ${fmtPct(sh.late_rate_to)})`) });
  }

  // ===== GROWTH (seller side)
  document.getElementById("page-growth").innerHTML =
    `<div class="grid g2">${card("c-sup", "Monthly GMV split by sellers in their first selling month vs existing sellers.", "chart tall")}
     ${card("c-tree", "GMV = active sellers × GMV per active seller; average month of Jun–Aug 2018 vs Mar–May 2018 (log decomposition).", "chart tall")}</div>
     <div style="height:14px"></div><div class="grid g2">
     ${card("c-funnel", "Olist Marketing Funnel: qualified leads → closed deals → sellers with at least one sale in the order data.")}
     ${card("c-cat", "Share of the Jan–Aug 2018 vs Jan–Aug 2017 GMV increase by category (item-level). Note: 2017 is the ramp-up base.")}</div>`;
  function renderGrowth() {
    const sup = R.growth.supply_side, mm = sup.monthly, t = sup.jun_aug_vs_mar_may_seller_tree;
    setT("c-sup", `New sellers bring only ${fmtPct(sup.new_seller_gmv_share_2018, 0)} of 2018 GMV; the plateau is in existing sellers' sales`);
    plot("c-sup", [
      { type: "bar", name: "existing sellers", x: mm.map((r) => r.m), y: mm.map((r) => r.gmv - r.gmv_new_sellers), marker: { color: COL.s1 }, hovertemplate: "%{x}: R$%{y:,.0f}<extra>existing</extra>" },
      { type: "bar", name: "sellers in first month", x: mm.map((r) => r.m), y: mm.map((r) => r.gmv_new_sellers), marker: { color: COL.s3 }, hovertemplate: "%{x}: R$%{y:,.0f}<extra>new</extra>" },
    ], { barmode: "stack", showlegend: true, yaxis: ax("GMV per month (BRL)", { tickprefix: "R$", tickformat: "~s" }), xaxis: ax("purchase month") });
    setT("c-tree", `Active sellers +${fmtPct(t.sellers_to / t.sellers_from - 1, 0)}, GMV per seller ${fmtPct(t.gmv_per_seller_to / t.gmv_per_seller_from - 1, 0)}: supply grew, demand did not`);
    const vals = [t.gmv_from, t.drivers.active_sellers.contribution_brl, t.drivers.gmv_per_seller.contribution_brl, t.gmv_to];
    plot("c-tree", [{ type: "waterfall", x: ["Mar–May avg", "More active sellers", "Less GMV per seller", "Jun–Aug avg"], y: vals,
      measure: ["absolute", "relative", "relative", "total"], connector: { line: { color: COL.grid } },
      increasing: { marker: { color: COL.s3 } }, decreasing: { marker: { color: COL.s2 } }, totals: { marker: { color: COL.neutral } },
      text: vals.map(fmtBRL), textposition: "outside", hovertemplate: "%{x}: %{y:,.0f} BRL<extra></extra>" }],
      { yaxis: ax("GMV per month (BRL)", { tickprefix: "R$", tickformat: "~s" }) });
    const f = sup.funnel;
    setT("c-funnel", `${fmtPct(f.win_rate, 1)} of qualified leads become sellers and ${fmtPct(f.sold_rate_of_won, 0)} of those ever sell; funnel sellers = ${fmtPct(f.funnel_seller_share_of_2018_gmv, 0)} of 2018 GMV`);
    plot("c-funnel", [{ type: "bar", x: ["Qualified leads", "Closed deals", "Sold at least once"], y: [f.mqls, f.won, f.sold], marker: { color: [COL.neutral, COL.s1, COL.s3] },
      text: [f.mqls, f.won, f.sold].map(fmtN), textposition: "outside", hovertemplate: "%{x}: %{y:,}<extra></extra>" }],
      { yaxis: ax("count (Jun-2017–Jun-2018 leads)") });
    const rows = R.growth.ytd_category_contribution.slice(0, 8).reverse();
    setT("c-cat", `No category added more than ${fmtPct(rows[rows.length - 1].share_of_growth, 0)} of the YoY increase: broad-based ramp-up`);
    plot("c-cat", [{ type: "bar", orientation: "h", y: rows.map((r) => nice(r.segment)), x: rows.map((r) => r.share_of_growth), marker: { color: COL.s1 },
      text: rows.map((r) => fmtPct(r.share_of_growth, 0)), textposition: "outside", cliponaxis: false, hovertemplate: "%{y}: %{x:.1%}<extra></extra>" }],
      { margin: { l: 160, r: 40, t: 8, b: 44 }, xaxis: ax("share of YoY GMV increase", { tickformat: ".0%" }) });
  }

  // ===== CUSTOMERS
  document.getElementById("page-customers").innerHTML =
    `<div class="grid g2">${card("c-km", "Kaplan–Meier cumulative probability of a 2nd order (handles right-censoring). 'Later day' excludes same-day split baskets: the governed repeat definition.", "chart tall")}
     <div class="card"><h2>Metric governance: when the "same" KPI disagrees</h2><p class="cap">The governed definition is in metrics/metrics.yml; rejected ones are kept there with the reason.</p><div id="gov"></div>
     <div class="callout" id="cust-text" style="margin-top:12px"></div></div></div>`;
  function renderCustomers() {
    const K = R.cohorts, days = [7, 30, 90, 180, 365];
    setT("c-km", `Only ${fmtPct(K.km_cumulative_2nd_order_later_day["180"])} of buyers return on a later day within 180 days`);
    plot("c-km", [
      { type: "scatter", mode: "lines+markers", name: "any 2nd order (incl. same-day baskets)", x: days, y: days.map((d) => K.km_cumulative_2nd_order_any[d]), line: { color: COL.s2, width: 2 }, marker: { size: 8 }, hovertemplate: "day %{x}: %{y:.2%}<extra></extra>" },
      { type: "scatter", mode: "lines+markers", name: "2nd order on a later day (governed)", x: days, y: days.map((d) => K.km_cumulative_2nd_order_later_day[d]), line: { color: COL.s1, width: 2 }, marker: { size: 8 }, hovertemplate: "day %{x}: %{y:.2%}<extra></extra>" },
    ], { showlegend: true, xaxis: ax("days since first order"), yaxis: ax("cumulative share with a 2nd order", { tickformat: ".1%", rangemode: "tozero" }) });
    const MC = R.metric_conflicts, rr = MC.customer_identity.repeat_rate, ot = MC.on_time_delivery, om = ot.largest_monthly_gaps_purchase_vs_delivery_month[0], gv = MC.gmv.variants;
    document.getElementById("gov").innerHTML = `<table>
      <tr><th>KPI</th><th>Governed</th><th>Plausible alternative</th><th class="n">Gap</th></tr>
      <tr><td>On-time, ${om.month.slice(0, 7)}</td><td>by purchase month: ${fmtPct(om.purchase_cohort_on_time)}</td><td>by delivery month: ${fmtPct(om.delivery_month_on_time)}</td><td class="n">${om.gap_pp.toFixed(1)} pp</td></tr>
      <tr><td>Repeat rate (lifetime)</td><td>bought on 2+ days: ${fmtPct(rr.governed_lifetime_share_bought_on_2plus_days, 2)}</td><td>2+ orders incl. same-day: ${fmtPct(rr.rejected_counting_same_day_orders, 2)}</td><td class="n">+${fmtPct(rr.rejected_counting_same_day_orders / rr.governed_lifetime_share_bought_on_2plus_days - 1, 0)}</td></tr>
      <tr><td>On-time (all time)</td><td>date compare: ${fmtPct(ot.all_time.governed_date_compare)}</td><td>timestamp compare: ${fmtPct(ot.all_time.rejected_timestamp_compare)}</td><td class="n">${ot.all_time.gap_pp.toFixed(1)} pp</td></tr>
      <tr><td>GMV (all time)</td><td>item price: ${fmtBRL(gv["governed: item price, revenue orders"].total_brl)}</td><td>incl. freight: ${fmtBRL(gv["incl. freight"].total_brl)}</td><td class="n">+${fmtBRL(gv["incl. freight"].total_brl - gv["governed: item price, revenue orders"].total_brl)}</td></tr></table>`;
    const rep = R.delivery_impact.repurchase;
    document.getElementById("cust-text").innerHTML = `Repeat buying is rare (${fmtPct(rr.governed_lifetime_share_bought_on_2plus_days)} of buyers ever return on a later day), so lifetime value ≈ the first order.
      Late delivery shifts 180-day repurchase by ${sgn(100 * rep.fe_lpm.estimate)} pp, but the test can only detect ≥ ${(100 * rep.mde_80pct_power).toFixed(2)} pp (${fmtPct(rep.mde_relative_to_base, 0)} of the base): <b>underpowered, not "no effect"</b>.`;
  }

  // ===== DELIVERY & PROMISE
  document.getElementById("page-delivery").innerHTML =
    `<div class="card"><h2 id="t-sim"></h2>
      <p class="cap">Rolling backtest with no look-ahead; never-delivered orders count as late. The policy is chosen on Oct-2017–Mar-2018 and reported on Apr–Aug 2018. Review cost uses the dose-response for the chosen survey regime. The conversion upside is not measured: the break-even is the lift per promise-day needed to cover the cost.</p>
      <div class="sim-controls"><label>Policy <select id="sim-policy"></select></label><label>Period <select id="sim-period"></select></label>
      <label>Survey regime <select id="sim-regime"><option value="survey_today">today (promise + 2 days)</option><option value="survey_on_delivery">on confirmed delivery</option></select></label></div>
      <div class="sim-out" id="sim-out"></div>
      <div class="grid g2" style="margin-top:10px"><div id="c-frontier" class="chart"></div><div id="c-pad" class="chart"></div></div></div>
     <div style="height:14px"></div>
     <div class="grid g2">${card("c-dose", "Fixed effects (seller, category, state, month) + controls; 95% CI; SE clustered by seller. Reference: 1–7 days early.", "chart tall")}
     ${card("c-inflight", "Share of open orders already past their promised date, computed daily from data available that day. Alert: z ≥ 3 vs trailing 56-day median, 2 days in a row.", "chart tall")}</div>
     <div style="height:14px"></div>
     <div class="grid g2"><div class="card"><h2 id="t-lanes"></h2><p class="cap">Sep-2017–Aug-2018, lanes with ≥100 delivered orders. Expected = lane-adjusted baseline (distance, destination state, origin region, month). No carrier ID in the data, so the late remainder mixes carrier transit and promise error.</p><div id="lanes"></div></div>
     ${card("c-anom", "Order-volume monitor: one-step-ahead STL forecast on the trailing 84 days; alert when |z| ≥ 4 (or ≥ 3 on both orders and GMV). Calendar events are annotated, not paged.", "chart tall")}</div>`;
  function renderDelivery() {
    const P = R.promise_policy, pol = P.policies;
    const sel = document.getElementById("sim-policy"), per = document.getElementById("sim-period"), reg = document.getElementById("sim-regime");
    if (!sel.options.length) {
      Object.keys(pol.full_year).forEach((k) => sel.add(new Option(nice(k).replace("Lane q", "Lane P"), k)));
      [["full_year", "full year Oct-2017–Aug-2018"], ["selection", "selection Oct–Mar"], ["test", "test Apr–Aug 2018"]].forEach(([v, t]) => per.add(new Option(t, v)));
      sel.value = "lane_q80"; sel.onchange = per.onchange = reg.onchange = renderSim;
    }
    function renderSim() {
      const p = pol[per.value][sel.value], c = pol[per.value].current_olist_estimate, r = p[reg.value];
      setT("sim", `A lane-P80 promise saves ${pol.full_year.lane_q80.mean_days_saved_vs_current.toFixed(1)} days but the late rate goes ${fmtPct(pol.full_year.current_olist_estimate.late_rate)} → ${fmtPct(pol.full_year.lane_q80.late_rate)} over a full year`);
      const be = r.breakeven_conversion_lift_per_promise_day;
      const out = [
        ["Avg promise", p.mean_promise_days.toFixed(1) + " d", `today ${c.mean_promise_days.toFixed(1)} d`],
        ["Days saved vs today", sgn(p.mean_days_saved_vs_current, 1) + " d", "mean per order"],
        ["Late rate", fmtPct(p.late_rate), `${sgn(p.delta_late_pp, 1)} pp vs today ${fmtPct(c.late_rate)}`],
        ["Extra late orders / yr", fmtN(p.extra_late_orders_per_year), "annualised"],
        ["Expected avg review", sgn(r.expected_delta_avg_review, 3) + "★", reg.value === "survey_today" ? "under today's survey" : "if survey sent on delivery"],
        ["Extra 1–2★ reviews / yr", fmtN(r.extra_1_2_star_reviews_per_year), "annualised"],
        ["Cost / yr (measured)", fmtBRL(r.cost_brl_per_year), "repeat GMV + review panel (null)"],
        ["Break-even conversion lift", be == null ? "n/a (longer promise)" : (100 * be).toFixed(3) + "% / day", "needed to pay for the cost"],
      ];
      document.getElementById("sim-out").innerHTML = out.map(([n, v, s]) => `<div class="card kpi"><div class="name">${n}</div><div class="val">${v}</div><div class="row muted">${s}</div></div>`).join("");
      const qs = ["lane_q50", "lane_q60", "lane_q70", "lane_q80", "lane_q85", "lane_q90", "lane_q95", "lane_q99"].filter((k) => pol[per.value][k]);
      const pts = qs.map((k) => pol[per.value][k]);
      plot("c-frontier", [
        { type: "scatter", mode: "lines+markers+text", x: pts.map((v) => v.mean_days_saved_vs_current), y: pts.map((v) => v.late_rate), text: qs.map((k) => "P" + k.slice(6)), textposition: "top right",
          textfont: { size: 10, color: COL.text2 }, line: { color: COL.s1, width: 2 }, marker: { size: 8 }, name: "lane quantile", hovertemplate: "%{text}: saves %{x:.1f} d, late %{y:.1%}<extra></extra>" },
        { type: "scatter", mode: "markers", x: [0], y: [c.late_rate], marker: { size: 12, color: COL.text2, symbol: "diamond" }, name: "today", hovertemplate: "today: late %{y:.1%}<extra></extra>" },
        { type: "scatter", mode: "markers", x: [p.mean_days_saved_vs_current], y: [p.late_rate], marker: { size: 14, color: COL.s2, line: { color: "#fff", width: 2 } }, name: "selected", hovertemplate: "selected<extra></extra>" },
      ], { showlegend: true, xaxis: ax("promise days saved vs today (mean)"), yaxis: ax("late rate (never-delivered = late)", { tickformat: ".0%" }), margin: { l: 64, r: 16, t: 8, b: 44 } });
    }
    renderSim();
    const h = P.padding.padding_histogram, hx = Object.keys(h).map(Number).sort((a, b) => a - b);
    plot("c-pad", [{ type: "bar", x: hx, y: hx.map((x) => h[Object.keys(h).find((k) => Number(k) === x)]), marker: { color: hx.map((x) => (x < 0 ? COL.s2 : COL.s1)) }, hovertemplate: "%{x} days early: %{y:,} orders<extra></extra>" }],
      { xaxis: ax(`promised − actual days (median ${P.padding.overall_quantiles.p50} days early; negative = late)`), yaxis: ax("delivered orders") });
    const DI = R.delivery_impact, a = DI.review.G_dose_response.fe, b = DI.review_post_delivery.G_dose_response.fe;
    setT("c-dose", `Rated after delivery, 4–7 days late costs ${Math.abs(b[5].effect).toFixed(1)}★, not the ${Math.abs(a[5].effect).toFixed(1)}★ the platform records`);
    plot("c-dose", [[a, "all reviews (as recorded)", COL.s2], [b, "reviews written after delivery", COL.s1]].map(([s, n, c]) => ({
      type: "scatter", mode: "lines+markers", name: n, x: s.map((r) => r.bin), y: s.map((r) => r.effect),
      error_y: { type: "data", symmetric: false, array: s.map((r) => r.ci95[1] - r.effect), arrayminus: s.map((r) => r.effect - r.ci95[0]), color: c, thickness: 1.5, width: 3 },
      line: { color: c, width: 2 }, marker: { size: 8 }, hovertemplate: "%{x}: %{y:.2f}★<extra>" + n + "</extra>" })),
      { showlegend: true, yaxis: ax("Δ review score vs 1–7 days early (stars)"), xaxis: ax("delivered vs promised date") });
    const I = R.anomalies.inflight_late_monitor, s2 = I.series, al = I.alert_days;
    setT("c-inflight", `In-flight lateness flags the spring-2018 slump on ${I.first_alert_by_incident.feb_mar_2018_slowdown}; the volume monitor never alerted in Feb–Mar`);
    plot("c-inflight", [
      { type: "scatter", mode: "lines", x: s2.map((r) => r.day), y: s2.map((r) => r.share_past_promise), line: { color: COL.s1, width: 1.5 }, name: "share past promise", hovertemplate: "%{x|%Y-%m-%d}: %{y:.1%}<extra></extra>" },
      { type: "scatter", mode: "markers", x: al.map((r) => r.day), y: al.map((r) => r.share_past_promise), marker: { size: 8, color: COL.bad, symbol: "x" }, name: "alert", hovertemplate: "alert %{x|%Y-%m-%d}<extra></extra>" },
    ], { showlegend: true, yaxis: ax("open orders past promise", { tickformat: ".0%" }), xaxis: ax("day") });
    const L = R.lanes, wl = L.worst_lanes.slice(0, 8);
    setT("lanes", `Against a lane-adjusted baseline only ${fmtN(L.summary.top10_excess_late_orders)} late orders/yr are excess in the 10 worst lanes (vs ${fmtN(L.summary.excess_vs_network_top10_old_method)} vs network average)`);
    document.getElementById("lanes").innerHTML = `<table><tr><th>Lane</th><th class="n">Orders</th><th class="n">Late</th><th class="n">Expected</th><th class="n">Excess late</th><th class="n">Seller handed over late</th><th class="n">1–2★ avoidable (rec./post)</th></tr>` +
      wl.map((r) => `<tr><td>${nice(r.lane)}</td><td class="n">${fmtN(r.delivered_orders)}</td><td class="n">${fmtPct(r.late_rate)}</td><td class="n">${fmtPct(r.expected_late_rate_lane_adjusted)}</td><td class="n">${fmtN(r.excess_late_orders)}</td><td class="n">${fmtPct(r.late_share_seller_handover_missed, 0)}</td><td class="n">${fmtN(r.low_reviews_avoidable)} / ${fmtN(r.low_reviews_avoidable_post_delivery)}</td></tr>`).join("") + "</table>";
    const A = R.anomalies, s = A.series, al2 = A.online_alerts;
    setT("c-anom", `${A.n_online_investigate} of ${A.n_online_alerts} volume alerts needed a human; Black Friday 2017 (${A.black_friday_2017.multiple_of_expected_orders.toFixed(1)}× expected) was annotated`);
    plot("c-anom", [
      { type: "scatter", mode: "lines", x: s.map((r) => r.date), y: s.map((r) => r.orders), line: { color: COL.s1, width: 1.5 }, name: "orders", hovertemplate: "%{x}: %{y} orders<extra></extra>" },
      { type: "scatter", mode: "markers", x: al2.map((r) => r.date), y: al2.map((r) => r.orders), name: "alert", marker: { size: 9, symbol: al2.map((r) => (r.classification === "expected_event" ? "diamond" : "x")), color: al2.map((r) => (r.classification === "expected_event" ? COL.s3 : COL.bad)) },
        customdata: al2.map((r) => [r.classification.replace("_", " "), r.known_event || ""]), hovertemplate: "%{x}<br>%{customdata[0]} %{customdata[1]}<extra></extra>" },
    ], { showlegend: true, yaxis: ax("orders per day"), xaxis: ax("purchase date") });
  }

  // ===== SELLERS & VOC
  document.getElementById("page-sellers").innerHTML =
    `<div class="grid g2">${card("c-voc", "Keyword classifier on every 1–2★ review with text of an on-time order. Shares corrected for misclassification (confusion matrix vs single-annotator labels), 95% bootstrap CI.", "chart tall")}
     <div class="card"><h2 id="t-tiers"></h2><p class="cap">Sep-2017–Aug-2018. Tier = scale (top-10% GMV) × quality bar (on-time ≥ network − 3 pp, review ≥ network − 0.2). In a seller-week panel, bad reviews did not measurably reduce later seller GMV.</p><div id="tiers"></div></div></div>`;
  function renderSellers() {
    const V = R.voc, c = V.negative_on_time_share_corrected_for_misclassification;
    const labs = Object.keys(c).filter((k) => k !== "positive").sort((x, y) => c[x].corrected - c[y].corrected);
    const top = labs.slice(-2).reverse();
    setT("c-voc", `On orders delivered on time, the top complaints are ${nice(top[0]).toLowerCase()} (${fmtPct(c[top[0]].corrected, 0)}) and ${nice(top[1]).toLowerCase()} (${fmtPct(c[top[1]].corrected, 0)}); CIs overlap`);
    plot("c-voc", [{ type: "bar", orientation: "h", y: labs.map(nice), x: labs.map((l) => c[l].corrected), marker: { color: COL.s1 },
      error_x: { type: "data", symmetric: false, array: labs.map((l) => c[l].ci95[1] - c[l].corrected), arrayminus: labs.map((l) => Math.max(0, c[l].corrected - c[l].ci95[0])), color: COL.text2, thickness: 1.2 },
      customdata: labs.map((l) => c[l].observed), hovertemplate: "%{y}: %{x:.1%} corrected (raw %{customdata:.1%})<extra></extra>" }],
      { margin: { l: 150, r: 16, t: 8, b: 44 }, xaxis: ax("share of 1–2★ reviews on on-time orders", { tickformat: ".0%" }) });
    const S = R.sellers, t2 = S.tiers.find((t) => t.tier.startsWith("T2"));
    setT("tiers", `${t2.sellers} large sellers below the quality bar hold ${fmtPct(t2.gmv_share, 0)} of GMV at ${fmtPct(t2.on_time, 0)} on-time`);
    document.getElementById("tiers").innerHTML = `<table><tr><th>Tier</th><th class="n">Sellers</th><th class="n">GMV share</th><th class="n">On-time</th><th class="n">Review</th></tr>` +
      S.tiers.map((t) => `<tr><td>${nice(t.tier)}</td><td class="n">${fmtN(t.sellers)}</td><td class="n">${fmtPct(t.gmv_share)}</td><td class="n">${fmtPct(t.on_time)}</td><td class="n">${t.review.toFixed(2)}</td></tr>`).join("") +
      `</table><p class="cap" style="margin-top:8px">Top-10% of sellers earn ${fmtPct(S.pareto.top_10pct_sellers_share, 0)} of GMV (HHI ${S.hhi_window.toFixed(0)}: unconcentrated).</p>`;
  }

  // ===== ROOT CAUSE
  document.getElementById("page-rca").innerHTML =
    `<div class="card"><h2>Automated root cause: pick a KPI move</h2><p class="cap">Moves are found automatically (largest month-over-month changes). Each is split into mix (volume moved between segments) and rate (segments themselves changed) for six dimensions, including process stage (fulfilment leg) and lane. A driver is named only when the move is concentrated.</p>
     <div class="sim-controls"><label>Move <select id="rca-move"></select></label></div><div id="rca-summary" class="callout"></div></div>
     <div style="height:14px"></div><div class="grid g3">${card("c-rca-0", "")}${card("c-rca-1", "")}${card("c-rca-2", "")}</div>`;
  function renderRCA() {
    const RC = R.root_cause, selm = document.getElementById("rca-move");
    if (!selm.options.length) {
      RC.moves.forEach((m, i) => selm.add(new Option(`${D.meta[m.kpi].label}: ${m.from_month.slice(0, 7)} → ${m.to_month.slice(0, 7)}`, i)));
      const def = RC.moves.findIndex((m) => m.kpi === "on_time_delivery_rate" && m.to_month.startsWith("2018-03"));
      selm.value = def >= 0 ? def : 0; selm.onchange = renderRCA;
    }
    const m = RC.moves[+selm.value], dims = m.dimension_ranking_by_surprise, d0 = m.by_dimension[dims[0]];
    const sp = m.stages;
    const stageTxt = sp ? ` By process stage: promise ${sgn(sp.shapley_pp.promise, 1)} pp, seller handling ${sgn(sp.shapley_pp.seller_days, 1)} pp, carrier transit ${sgn(sp.shapley_pp.transit, 1)} pp (late rate ${fmtPct(sp.late_rate_from)} → ${fmtPct(sp.late_rate_to)}).` : "";
    document.getElementById("rca-summary").innerHTML = `<b>${D.meta[m.kpi].label}</b> ${fmt(m.kpi, d0.kpi_from)} → ${fmt(m.kpi, d0.kpi_to)}. <b>Verdict: ${m.verdict.text.replace(/_/g, " ")}.</b>${stageTxt}`;
    ["c-rca-0", "c-rca-1", "c-rca-2"].forEach((id, j) => {
      const dim = dims[j], d = m.by_dimension[dim], rows = d.top_segments.slice(0, 7).reverse();
      setT(id, `${nice(dim)}: top segments explain ${fmtPct(d.top3_share_of_abs_movement, 0)} of the movement`);
      document.getElementById(id).previousElementSibling.textContent = d.rate_effect == null ? "Change in BRL by segment." : `Contribution to the change (${m.kpi === "on_time_delivery_rate" ? "share points" : "stars"}), split into rate and mix.`;
      const traces = d.rate_effect == null
        ? [{ type: "bar", orientation: "h", y: rows.map((r) => nice(r.segment)), x: rows.map((r) => r.contribution), marker: { color: rows.map((r) => (r.contribution >= 0 ? COL.s1 : COL.s2)) }, hovertemplate: "%{y}: %{x:,.0f} BRL<extra></extra>" }]
        : [["rate", "rate (within segment)", COL.s1], ["mix", "mix (volume shift)", COL.s2]].map(([k, n, c]) => ({
            type: "bar", orientation: "h", name: n, y: rows.map((r) => nice(r.segment)), x: rows.map((r) => r[k]), marker: { color: c }, hovertemplate: "%{y} " + n + ": %{x:.4f}<extra></extra>" }));
      plot(id, traces, { barmode: "relative", showlegend: d.rate_effect != null && j === 0, margin: { l: 150, r: 12, t: 8, b: 44 },
        xaxis: ax(d.rate_effect == null ? "BRL" : m.kpi === "on_time_delivery_rate" ? "on-time rate change" : "stars") });
    });
  }

  // ---------- filter wiring
  const fFrom = document.getElementById("f-from"), fTo = document.getElementById("f-to"), fS = document.getElementById("f-state"), fC = document.getElementById("f-cat");
  M.forEach((m, i) => { fFrom.add(new Option(m, i)); fTo.add(new Option(m, i)); });
  fFrom.value = st.from; fTo.value = st.to;
  fS.add(new Option("All states", "ALL")); C.states.forEach((s) => fS.add(new Option(s, s)));
  fC.add(new Option("All categories", "ALL")); C.categories.forEach((c) => fC.add(new Option(nice(c), c)));
  function onFilter() {
    st.from = Math.min(+fFrom.value, +fTo.value); st.to = Math.max(+fFrom.value, +fTo.value);
    st.state = fS.value; st.cat = fC.value; renderExec();
  }
  [fFrom, fTo, fS, fC].forEach((el) => (el.onchange = onFilter));
  window.__setFilters = (o) => { if (o.state) fS.value = o.state; if (o.cat) fC.value = o.cat; if (o.from != null) fFrom.value = o.from; if (o.to != null) fTo.value = o.to; onFilter(); };

  const rendered = {};
  const renderers = { exec: () => { renderExecStatic(); renderExec(); }, growth: renderGrowth, customers: renderCustomers, delivery: renderDelivery, sellers: renderSellers, rca: renderRCA };
  function show() {
    const id = (location.hash || "#exec").slice(1), pid = renderers[id] ? id : "exec";
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + pid));
    document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.page === pid));
    document.getElementById("filters").style.display = pid === "exec" ? "flex" : "none";
    if (!rendered[pid]) { renderers[pid](); rendered[pid] = true; }
    window.dispatchEvent(new Event("resize"));
  }
  window.addEventListener("hashchange", show);
  show();
  window.__ready = true;
})();
