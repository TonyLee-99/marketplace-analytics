/* Marketplace executive dashboard. Data: window.DATA (built by marketplace.dashboard.build).
   No KPI formula lives here: ratio KPIs = sum(num)/sum(den) of governed components;
   derived KPIs evaluate the formula string from metrics.yml. */
(function () {
  "use strict";
  const D = window.DATA, R = D.reports, C = D.cube;
  const css = (v) => getComputedStyle(document.body).getPropertyValue(v).trim();
  const COL = { s1: css("--series-1"), s2: css("--series-2"), s3: css("--series-3"), s4: css("--series-4"),
                good: css("--good"), bad: css("--critical"), muted: css("--text-muted"), grid: css("--grid"),
                neutral: css("--neutral"), text: css("--text-primary"), text2: css("--text-secondary") };

  // ---------- formatting
  const fmtBRL = (v) => v == null ? "–" : (Math.abs(v) >= 1e6 ? "R$" + (v / 1e6).toFixed(2) + "M"
                  : Math.abs(v) >= 1e3 ? "R$" + (v / 1e3).toFixed(1) + "k" : "R$" + v.toFixed(0));
  const fmtN = (v) => v == null ? "–" : Math.round(v).toLocaleString("en-US");
  const fmtPct = (v, d = 1) => v == null ? "–" : (100 * v).toFixed(d) + "%";
  const fmtPP = (v, d = 1) => (v >= 0 ? "+" : "") + (100 * v).toFixed(d) + " pp";
  const fmtSigned = (v, d = 2) => (v >= 0 ? "+" : "") + v.toFixed(d);
  const fmt = (name, v) => {
    const u = (D.meta[name] || {}).unit;
    if (u === "BRL") return fmtBRL(v);
    if (u === "ratio") return fmtPct(v);
    if (u === "count") return fmtN(v);
    if (u === "days") return v == null ? "–" : v.toFixed(1) + " d";
    if (u === "points") return v == null ? "–" : v.toFixed(1);
    return v == null ? "–" : v.toFixed(2);
  };

  // ---------- plotly base layout (recessive grid, no chart junk)
  const base = (extra = {}) => Object.assign({
    margin: { l: 52, r: 16, t: 8, b: 40 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "-apple-system, Segoe UI, Helvetica, Arial, sans-serif", size: 12, color: COL.text2 },
    xaxis: { gridcolor: COL.grid, zeroline: false, linecolor: COL.grid, automargin: true },
    yaxis: { gridcolor: COL.grid, zeroline: false, automargin: true },
    hovermode: "closest", hoverlabel: { bgcolor: "#fff", bordercolor: COL.grid, font: { color: COL.text } },
    showlegend: false, legend: { orientation: "h", y: 1.12, x: 0 },
  }, extra);
  const cfg = { displayModeBar: false, responsive: true };
  const plot = (id, traces, layout) => Plotly.react(id, traces, base(layout), cfg);

  // ---------- filters
  const st = { from: 0, to: C.months.length - 1, state: "ALL", cat: "ALL" };
  function aggregate(fromIdx, toIdx, byMonth) {
    // returns {metric: value} or {month: {metric: value}}
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
      for (const k of C.metrics) {
        const a = acc[key][k];
        vals[k] = !a ? null : a.hasDen ? (a.den ? a.num / a.den : null) : a.num;
      }
      for (const [d, f] of Object.entries(D.derived)) {
        try { vals[d] = Function(...Object.keys(vals), "return " + f)(...Object.values(vals)); }
        catch (e) { vals[d] = null; }
      }
      out[key] = vals;
    }
    return byMonth ? out : out[0] || {};
  }
  function activeCustomers(fromIdx, toIdx) {
    let src = null;
    if (st.state !== "ALL" && st.cat !== "ALL") return null;
    if (st.state !== "ALL") src = D.active.state[st.state];
    else if (st.cat !== "ALL") src = st.cat === "other" ? null : D.active.category[st.cat];
    else src = D.active.all;
    if (!src) return null;
    let s = 0, n = 0;
    for (let i = fromIdx; i <= toIdx; i++) { const v = src[C.months[i]]; if (v != null) { s += v; n++; } }
    return n ? s / n : null;
  }
  function target(name, monthly, fromIdx, toIdx) {
    const t = (D.meta[name] || {}).target;
    if (!t) return null;
    if (t.kind === "fixed") return t.value;
    if (t.kind === "momentum") {        // trailing 3-month average x (1 + uplift), summed over range
      const r = momentum(name, monthly, fromIdx, toIdx);
      return r ? r.target : null;
    }
    return null;
  }

  // Momentum plan, summed over the months in range that have 3 prior months of history.
  // Returns the plan and the actual over exactly those months (like-for-like variance).
  function momentum(name, monthly, fromIdx, toIdx) {
    const t = (D.meta[name] || {}).target;
    let tg = 0, act = 0, n = 0;
    for (let i = fromIdx; i <= toIdx; i++) {
      const prev = [i - 1, i - 2, i - 3].map((j) => monthly[j] && monthly[j][name]).filter((v) => v != null);
      if (prev.length < 3 || !monthly[i] || monthly[i][name] == null) continue;
      tg += (prev.reduce((a, b) => a + b, 0) / 3) * (1 + t.uplift); act += monthly[i][name]; n++;
    }
    return n ? { target: tg, actual: act, months: n } : null;
  }

  // ---------- pages
  const PAGES = [
    ["exec", "Executive KPIs"], ["growth", "Growth"], ["customers", "Customers & Retention"],
    ["delivery", "Delivery & Promise"], ["sellers", "Sellers & Voice of Customer"], ["rca", "Why did it move?"],
  ];
  const main = document.getElementById("main"), nav = document.getElementById("nav");
  PAGES.forEach(([id, label]) => {
    const b = document.createElement("button"); b.textContent = label; b.dataset.page = id;
    b.onclick = () => { location.hash = id; }; nav.appendChild(b);
    const p = document.createElement("section"); p.className = "page"; p.id = "page-" + id; main.appendChild(p);
  });
  const card = (id, title, cap, cls = "chart", badge = false) =>
    `<div class="card"><h2 id="t-${id}">${title}${badge ? '<span class="badge">filters</span>' : ""}</h2>` +
    `<p class="cap">${cap}</p><div id="${id}" class="${cls}"></div></div>`;

  // ===== EXECUTIVE
  const KPI_LIST = ["gmv", "orders", "aov", "active_customers", "on_time_delivery_rate", "avg_review_score",
                    "nps_style_score", "cancellation_rate"];
  document.getElementById("page-exec").innerHTML =
    `<div class="grid g4" id="kpis"></div><div style="height:14px"></div>
     <div class="grid g2">${card("c-gmv", "", "Governed GMV (item price, revenue orders, by purchase date) vs momentum plan (trailing 3-month avg +3%).", "chart", true)}
     ${card("c-ontime", "", "On-time = delivered on or before the promised date, by purchase month. Dashed = 93% target.", "chart", true)}</div>
     <div style="height:14px"></div><div class="grid g2">
     <div class="card"><h2>What moved, and why (automated root cause)</h2><p class="cap">Largest month-over-month KPI moves, decomposed by state, category and seller tier. Details: "Why did it move?" tab.</p><div id="exec-rca"></div></div>
     <div class="card"><h2>Three decisions on the table</h2><p class="cap">From docs/exec_memo.md. Impact sized on real data; confidence stated.</p><div id="exec-recs"></div></div></div>`;

  function renderExec() {
    const sel = aggregate(st.from, st.to, false);
    const monthly = aggregate(0, C.months.length - 1, true);
    const len = st.to - st.from + 1;
    const pf = st.from - len, pt = st.from - 1;
    const prior = pf >= 0 ? aggregate(pf, pt, false) : null;
    sel.active_customers = activeCustomers(st.from, st.to);
    if (prior) prior.active_customers = activeCustomers(pf, pt);
    const lowerBetter = { cancellation_rate: true };
    document.getElementById("kpis").innerHTML = KPI_LIST.map((k) => {
      const v = sel[k], m = D.meta[k];
      let tg = target(k, monthly, st.from, st.to), vt = v, planNote = "";
      if (m.target && m.target.kind === "momentum") {
        const mo = momentum(k, monthly, st.from, st.to);
        if (mo) { vt = mo.actual; planNote = mo.months < len ? ` (${mo.months} mo with plan)` : ""; }
      }
      let tgt = "";
      if (tg != null && vt != null) {
        const v = vt;
        const diff = m.unit === "ratio" ? v - tg : (v / tg - 1);
        const good = lowerBetter[k] ? diff <= 0 : diff >= 0;
        const txt = m.unit === "ratio" ? fmtPP(diff) : (m.unit === "points" || m.unit === "score")
          ? fmtSigned(v - tg, m.unit === "points" ? 1 : 2) : (diff >= 0 ? "+" : "") + (100 * diff).toFixed(1) + "%";
        tgt = `<span class="pill ${good ? "good" : "bad"}">${good ? "▲" : "▼"} ${txt} vs ${m.target.kind === "momentum" ? "plan" + planNote : "target " + fmt(k, tg)}</span>`;
      }
      let pr = "";
      if (prior && prior[k] != null && v != null) {
        const d = m.unit === "ratio" ? fmtPP(v - prior[k]) : (m.unit === "points" || m.unit === "score")
          ? fmtSigned(v - prior[k]) : ((v / prior[k] - 1) >= 0 ? "+" : "") + (100 * (v / prior[k] - 1)).toFixed(1) + "%";
        pr = `<span class="muted">${d} vs prior ${len} mo</span>`;
      }
      const name = k === "active_customers" ? "Active customers (avg / month)" : m.label;
      return `<div class="card kpi" title="${m.definition.replace(/"/g, "'")}"><div class="name">${name}</div>
              <div class="val">${fmt(k, v)}</div><div class="row">${tgt}${pr}</div></div>`;
    }).join("");

    const months = C.months.slice(st.from, st.to + 1);
    const g = months.map((_, i) => (monthly[st.from + i] || {}).gmv);
    const tg = months.map((_, i) => target("gmv", monthly, st.from + i, st.from + i));
    const lastI = g.length - 1;
    const yoyIdx = st.to - 12;
    let t1 = "GMV by month vs plan";
    if (yoyIdx >= 0 && monthly[yoyIdx] && monthly[st.to]) {
      const y = monthly[st.to].gmv / monthly[yoyIdx].gmv - 1;
      t1 = `GMV in ${months[lastI]} was ${fmtBRL(g[lastI])}, ${(100 * y).toFixed(0)}% above a year earlier`;
    }
    document.getElementById("t-c-gmv").innerHTML = t1 + '<span class="badge">filters</span>';
    plot("c-gmv", [
      { type: "bar", x: months, y: g, marker: { color: COL.s1 }, name: "GMV", hovertemplate: "%{x}<br>GMV R$%{y:,.0f}<extra></extra>" },
      { type: "scatter", mode: "lines", x: months, y: tg, line: { color: COL.text2, width: 2, dash: "dot" }, name: "Plan", hovertemplate: "Plan R$%{y:,.0f}<extra></extra>" },
    ], { yaxis: { gridcolor: COL.grid, tickprefix: "R$", tickformat: "~s" }, showlegend: true });

    const ot = months.map((_, i) => (monthly[st.from + i] || {}).on_time_delivery_rate);
    const worst = ot.reduce((a, v, i) => (v != null && (a < 0 || v < ot[a]) ? i : a), -1);
    document.getElementById("t-c-ontime").innerHTML = (worst >= 0
      ? `On-time delivery bottomed at ${fmtPct(ot[worst])} for ${months[worst]} orders; target is 93%`
      : "On-time delivery rate") + '<span class="badge">filters</span>';
    plot("c-ontime", [
      { type: "scatter", mode: "lines+markers", x: months, y: ot, line: { color: COL.s1, width: 2 }, marker: { size: 8 },
        hovertemplate: "%{x}<br>On-time %{y:.1%}<extra></extra>" },
      { type: "scatter", mode: "lines", x: months, y: months.map(() => 0.93), line: { color: COL.text2, width: 1.5, dash: "dash" }, hoverinfo: "skip" },
    ], { yaxis: { gridcolor: COL.grid, tickformat: ".0%", range: [0.75, 1] } });
  }
  function renderExecStatic() {
    document.getElementById("exec-rca").innerHTML = "<table><tr><th>KPI move</th><th>Main driver (auto)</th><th class='n'>Rate vs mix</th></tr>" +
      R.root_cause.moves.map((m) => {
        const dim = m.dimension_ranking_by_surprise[0], d = m.by_dimension[dim], top = d.top_segments[0];
        const rm = d.rate_effect == null ? "additive" : `rate ${fmtSigned(d.rate_effect, 3)} / mix ${fmtSigned(d.mix_effect, 3)}`;
        const label = D.meta[m.kpi].label;
        return `<tr><td>${label}: ${m.from_month.slice(0, 7)} → ${m.to_month.slice(0, 7)}<br><span class="muted">${fmt(m.kpi, d.kpi_from)} → ${fmt(m.kpi, d.kpi_to)}</span></td>
                <td>${dim}: <b>${top.segment}</b> (${m.kpi === "gmv" ? fmtBRL(top.contribution) : fmtSigned(top.contribution, 3)})</td><td class="n">${rm}</td></tr>`;
      }).join("") + "</table>";
    const pp = R.promise_policy, rec = pp.policies[pp.recommended_policy];
    const L = R.lanes.summary, S = R.sellers;
    document.getElementById("exec-recs").innerHTML = `<ol style="margin:0;padding-left:18px;line-height:1.5">
      <li><b>Recalibrate delivery promises</b> (${pp.recommended_policy.replace(/_/g, " ")}): promise ${rec.mean_days_saved_vs_current.toFixed(1)} days shorter on average; simulated late rate ${fmtPct(rec.late_rate_current)} → ${fmtPct(rec.late_rate)}; expected review ${fmtSigned(rec.expected_delta_avg_review, 3)} stars. Upside depends on conversion lift (not observable here): ${fmtBRL(rec["conversion_benefit_brl_per_year_sensitivity"]["0.25%_per_day"])}–${fmtBRL(rec["conversion_benefit_brl_per_year_sensitivity"]["1.00%_per_day"])}/yr. <span class="muted">Confidence: medium; A/B test first.</span></li>
      <li><b>Fix the worst lanes, starting with SP→RJ</b>: ${fmtN(L.top10_excess_late_orders)} excess late orders/yr in the 10 worst lanes ≈ ${fmtN(L.low_reviews_avoidable_top10)} fewer 1–2★ reviews. <span class="muted">Confidence: high on size, medium on fixability.</span></li>
      <li><b>Put the ${S.tiers.find((t) => t.tier.startsWith("T2")).sellers} "fix-first" sellers on a quality plan</b>: they hold ${fmtPct(S.tiers.find((t) => t.tier.startsWith("T2")).gmv_share)} of GMV with on-time ${fmtPct(S.tiers.find((t) => t.tier.startsWith("T2")).on_time)}. <span class="muted">Confidence: medium.</span></li></ol>`;
  }

  // ===== GROWTH
  document.getElementById("page-growth").innerHTML =
    `<div class="grid g2">${card("c-yoy", "", "Log (LMDI) decomposition: GMV = active customers × orders per customer × AOV. Bars add up exactly to the YoY change.", "chart tall")}
     ${card("c-tree", "", "Metric tree, Jan–Aug 2018 vs Jan–Aug 2017 (metrics layer, same filters as GMV).", "chart tall")}</div>
     <div style="height:14px"></div>
     <div class="grid g2">${card("c-cat", "", "Share of the Jan–Aug YoY GMV increase contributed by each category (item-level).")}
     ${card("c-state", "", "Share of the Jan–Aug YoY GMV increase contributed by each customer state.")}</div>`;
  function renderGrowth() {
    const G = R.growth, y = G.yoy, ytd = G.ytd_jan_aug_2018_vs_2017;
    const names = { active_customers: "Customers", orders_per_customer: "Orders / customer", aov: "AOV" };
    const cols = { active_customers: COL.s1, orders_per_customer: COL.s2, aov: COL.s3 };
    const share = ytd.drivers.active_customers.contribution_brl / ytd.delta_gmv;
    document.getElementById("t-c-yoy").textContent = `More customers explain ${(100 * share).toFixed(0)}% of 2018 GMV growth; frequency and AOV were flat`;
    plot("c-yoy", Object.keys(names).map((k) => ({
      type: "bar", name: names[k], x: y.map((r) => r.month), y: y.map((r) => r.drivers[k].contribution_brl),
      marker: { color: cols[k], line: { color: "#fcfcfb", width: 1 } },
      hovertemplate: names[k] + " %{y:,.0f} BRL<extra>%{x}</extra>",
    })), { barmode: "relative", showlegend: true, yaxis: { gridcolor: COL.grid, tickprefix: "R$", tickformat: "~s" } });
    document.getElementById("t-c-tree").textContent = `GMV +${(100 * ytd.pct_change).toFixed(0)}% YoY: customers +${(100 * ytd.drivers.active_customers.pct_change).toFixed(0)}%, orders/customer ${(100 * ytd.drivers.orders_per_customer.pct_change).toFixed(1)}%, AOV ${(100 * ytd.drivers.aov.pct_change).toFixed(1)}%`;
    const labels = ["GMV 2017", "Customers", "Orders / customer", "AOV", "GMV 2018"];
    const vals = [ytd.gmv_from, ytd.drivers.active_customers.contribution_brl, ytd.drivers.orders_per_customer.contribution_brl, ytd.drivers.aov.contribution_brl, ytd.gmv_to];
    plot("c-tree", [{ type: "waterfall", x: labels, y: vals, measure: ["absolute", "relative", "relative", "relative", "total"],
      connector: { line: { color: COL.grid } }, increasing: { marker: { color: COL.s1 } }, decreasing: { marker: { color: COL.s2 } },
      totals: { marker: { color: COL.neutral } }, text: vals.map(fmtBRL), textposition: "outside",
      hovertemplate: "%{x}: %{y:,.0f} BRL<extra></extra>" }], { yaxis: { gridcolor: COL.grid, tickprefix: "R$", tickformat: "~s" } });
    const bars = (id, rows, title) => {
      rows = rows.slice(0, 8).reverse();
      document.getElementById("t-" + id).textContent = title(rows[rows.length - 1]);
      plot(id, [{ type: "bar", orientation: "h", y: rows.map((r) => r.segment), x: rows.map((r) => r.share_of_growth),
        marker: { color: COL.s1 }, text: rows.map((r) => fmtPct(r.share_of_growth, 0)), textposition: "outside", cliponaxis: false,
        hovertemplate: "%{y}: %{x:.1%} of growth<extra></extra>" }], { margin: { l: 150, r: 40, t: 8, b: 30 }, xaxis: { gridcolor: COL.grid, tickformat: ".0%" } });
    };
    bars("c-cat", G.ytd_category_contribution, (r) => `Growth was broad-based: the top category (${r.segment}) added only ${fmtPct(r.share_of_growth, 0)} of it`);
    bars("c-state", G.ytd_state_contribution, (r) => `${r.segment} delivered ${fmtPct(r.share_of_growth, 0)} of growth vs ${fmtPct(r.share_of_gmv_from, 0)} of 2017 GMV: ${r.share_of_growth < r.share_of_gmv_from ? "other states grew faster" : "it outgrew the rest"}`);
  }

  // ===== CUSTOMERS
  document.getElementById("page-customers").innerHTML =
    `<div class="grid g2">${card("c-cohort", "", "Share of each monthly acquisition cohort (first order) that orders again k months later. Person = customer_unique_id.", "chart tall")}
     ${card("c-km", "", "Kaplan–Meier cumulative probability of a 2nd order (handles right-censoring). 'Later day' excludes same-day split baskets.", "chart tall")}</div>
     <div style="height:14px"></div><div class="grid g2">
     <div class="card"><h2>What a 3% repeat rate means for the business model</h2><div id="cust-text" class="callout"></div></div>
     <div class="card"><h2>Metric governance: the "same" KPI, two definitions</h2><p class="cap">Why the metrics layer pins definitions (reports/metric_conflicts.json).</p><div id="gov"></div></div></div>`;
  function renderCustomers() {
    const K = R.cohorts, coh = Object.entries(K.cohort_retention);
    const ks = Array.from({ length: 12 }, (_, i) => i + 1);
    const z = coh.map(([, v]) => ks.map((k) => v.retention[k] == null ? null : v.retention[k]));
    document.getElementById("t-c-cohort").textContent = `Fewer than 1% of new customers come back in any later month (month-1 avg ${fmtPct(K.avg_retention_curve["1"], 2)})`;
    plot("c-cohort", [{ type: "heatmap", x: ks.map((k) => "M+" + k), y: coh.map(([m]) => m), z,
      colorscale: [[0, "#f4f8fd"], [0.25, "#b7d3f6"], [0.5, "#6da7ec"], [0.75, "#2a78d6"], [1, "#104281"]], zmin: 0, zmax: 0.006,
      xgap: 2, ygap: 2, hovertemplate: "cohort %{y}, %{x}: %{z:.2%}<extra></extra>", colorbar: { tickformat: ".1%", thickness: 10 } }],
      { margin: { l: 70, r: 10, t: 8, b: 40 }, yaxis: { autorange: "reversed" } });
    const days = [7, 30, 90, 180, 365];
    document.getElementById("t-c-km").textContent = `Only ${fmtPct(K.km_cumulative_2nd_order_later_day["365"])} of customers place a 2nd order on a later day within a year`;
    plot("c-km", [
      { type: "scatter", mode: "lines+markers", name: "Any 2nd order", x: days, y: days.map((d) => K.km_cumulative_2nd_order_any[d]), line: { color: COL.s2, width: 2 }, marker: { size: 8 }, hovertemplate: "day %{x}: %{y:.2%}<extra>any</extra>" },
      { type: "scatter", mode: "lines+markers", name: "2nd order on a later day", x: days, y: days.map((d) => K.km_cumulative_2nd_order_later_day[d]), line: { color: COL.s1, width: 2 }, marker: { size: 8 }, hovertemplate: "day %{x}: %{y:.2%}<extra>later day</extra>" },
    ], { showlegend: true, xaxis: { gridcolor: COL.grid, title: "days since first order" }, yaxis: { gridcolor: COL.grid, tickformat: ".1%", rangemode: "tozero" } });
    document.getElementById("cust-text").innerHTML =
      `<b>${fmtPct(K.lifetime_repeat_rate)}</b> of ${fmtN(K.people)} buyers ever placed a 2nd order; repeat orders are <b>${fmtPct(K.repeat_gmv_share)}</b> of GMV,
       and ${fmtPct(K.share_of_next_orders_same_day, 0)} of "next orders" are same-day split baskets, not loyalty. Olist is an acquisition-driven marketplace:
       customer lifetime value ≈ the first order, so CAC has to pay back on the first order, and growth comes from new buyers and seller assortment.
       Retention programs should be judged against this ~2% base rate, and late delivery barely moves repurchase (see Delivery tab).`;
    const MC = R.metric_conflicts;
    const gv = MC.gmv.variants, ci = MC.customer_identity, ot = MC.on_time_delivery.all_time, om = MC.on_time_delivery.largest_monthly_gaps_purchase_vs_delivery_month[0];
    document.getElementById("gov").innerHTML = `<table>
      <tr><th>KPI</th><th>Governed</th><th>Plausible alternative</th><th class="n">Gap</th></tr>
      <tr><td>Repeat rate</td><td>customer_unique_id: ${fmtPct(ci.repeat_rate.governed_lifetime_share_of_people_with_2plus_orders)}</td><td>customer_id: ${fmtPct(ci.repeat_rate.rejected_customer_id_based)}</td><td class="n">every person looks new</td></tr>
      <tr><td>Active customers</td><td>${fmtN(ci.active_customers_all_time.governed_customer_unique_id)}</td><td>${fmtN(ci.active_customers_all_time.rejected_customer_id)}</td><td class="n">+${fmtPct(ci.active_customers_all_time.overcount_pct)}</td></tr>
      <tr><td>GMV (all time)</td><td>item price: ${fmtBRL(gv["governed: item price, revenue orders"].total_brl)}</td><td>incl. freight: ${fmtBRL(gv["incl. freight"].total_brl)}</td><td class="n">+${fmtBRL(gv["incl. freight"].total_brl - gv["governed: item price, revenue orders"].total_brl)}</td></tr>
      <tr><td>On-time (all time)</td><td>date compare: ${fmtPct(ot.governed_date_compare)}</td><td>timestamp compare: ${fmtPct(ot.rejected_timestamp_compare)}</td><td class="n">${ot.gap_pp.toFixed(1)} pp</td></tr>
      <tr><td>On-time ${om.month.slice(0, 7)}</td><td>by purchase month: ${fmtPct(om.purchase_cohort_on_time)}</td><td>by delivery month: ${fmtPct(om.delivery_month_on_time)}</td><td class="n">${om.gap_pp.toFixed(1)} pp</td></tr></table>`;
  }

  // ===== DELIVERY & PROMISE
  document.getElementById("page-delivery").innerHTML =
    `<div class="card"><h2 id="t-sim">Promise-policy simulator</h2>
      <p class="cap">Held-out purchases Apr–Aug 2018. Quantile models retrained monthly on data available before each month (no look-ahead). Review impact uses the same-delivery-time dose-response (the effect of moving the promise while the parcel arrives when it arrives).</p>
      <div class="sim-controls"><label>Policy <select id="sim-policy"></select></label>
      <label>Assumed conversion lift per promise-day saved <select id="sim-lift"></select></label><span class="muted" id="sim-rec"></span></div>
      <div class="sim-out" id="sim-out"></div>
      <div class="grid g2" style="margin-top:10px"><div id="c-frontier" class="chart"></div><div id="c-pad" class="chart"></div></div></div>
     <div style="height:14px"></div>
     <div class="grid g2">${card("c-dose", "", "Fixed-effects regression (seller, category, state, month + price, freight, items, distance), 95% CI, SE clustered by seller. Reference: 1–7 days early.", "chart tall")}
     ${card("c-rd", "", "Mean review score by days relative to the promised date (−10…+10). The drop starts at the promise, not at a delivery-time threshold.", "chart tall")}</div>
     <div style="height:14px"></div>
     <div class="grid g2"><div class="card"><h2 id="t-lanes"></h2><p class="cap">Seller state → customer state, ≥100 delivered orders, Sep-2017…Aug-2018. Excess = late orders above the network late rate.</p><div id="lanes"></div></div>
     ${card("c-anom", "", "Online monitor: one-step-ahead STL forecast on the trailing 84 days; alert when |z| ≥ 4 (or ≥ 3 on orders and GMV). Calendar events are annotated, not paged.", "chart tall")}</div>`;
  function renderDelivery() {
    const P = R.promise_policy, pol = P.policies;
    const sel = document.getElementById("sim-policy"), lift = document.getElementById("sim-lift");
    if (!sel.options.length) {
      Object.keys(pol).forEach((k) => { const o = document.createElement("option"); o.value = k; o.textContent = k.replace(/_/g, " "); sel.appendChild(o); });
      sel.value = P.recommended_policy;
      Object.keys(pol[P.recommended_policy].conversion_benefit_brl_per_year_sensitivity).forEach((k) => {
        const o = document.createElement("option"); o.value = k; o.textContent = k.replace("_", " "); lift.appendChild(o); });
      lift.selectedIndex = 1;
      sel.onchange = lift.onchange = renderSim;
    }
    function renderSim() {
      const p = pol[sel.value];
      document.getElementById("sim-rec").textContent = `Rule: shortest promise with late rate ≤ 7% and review change ≥ −0.05 → recommended: ${P.recommended_policy.replace(/_/g, " ")}`;
      const out = [
        ["Avg promise", p.mean_promise_days.toFixed(1) + " d", `current ${pol.current_olist_estimate.mean_promise_days.toFixed(1)} d`],
        ["Days saved vs today", fmtSigned(p.mean_days_saved_vs_current, 1) + " d", "mean per order"],
        ["Late rate", fmtPct(p.late_rate), `${fmtSigned(p.delta_late_pp, 1)} pp vs current ${fmtPct(p.late_rate_current)}`],
        ["Expected avg review", fmtSigned(p.expected_delta_avg_review, 3) + " ★", `1–2★ share ${fmtSigned(p.expected_delta_1_2_star_share_pp, 2)} pp`],
        ["Repurchase GMV at risk", fmtBRL(p.repurchase_gmv_at_risk_brl_per_year) + "/yr", `95% CI ${fmtBRL(p.repurchase_gmv_at_risk_brl_per_year_ci95[0])} … ${fmtBRL(p.repurchase_gmv_at_risk_brl_per_year_ci95[1])}`],
        ["Conversion upside (assumed)", fmtBRL(p.conversion_benefit_brl_per_year_sensitivity[lift.value]) + "/yr", "external elasticity, not measured"],
        ["Break-even lift / day", p.breakeven_conversion_lift_per_day == null ? "–" : (100 * p.breakeven_conversion_lift_per_day).toFixed(4) + "%", "vs repurchase loss only"],
        ["Late first orders added", fmtN(p.extra_late_first_orders_test), "in the 5 test months"],
      ];
      document.getElementById("sim-out").innerHTML = out.map(([n, v, s]) => `<div class="card kpi"><div class="name">${n}</div><div class="val">${v}</div><div class="row muted">${s}</div></div>`).join("");
      const ks = Object.keys(pol);
      plot("c-frontier", [{ type: "scatter", mode: "markers+text", x: ks.map((k) => pol[k].mean_days_saved_vs_current), y: ks.map((k) => pol[k].delta_late_pp),
        text: ks.map((k) => k.replace(/_/g, " ")), textposition: ks.map((k) => ({ lane_p90: "bottom right", model_p90_plus_2_days: "top right", current_olist_estimate: "top right" }[k] || "top center")), textfont: { size: 11, color: COL.text2 },
        marker: { size: ks.map((k) => (k === sel.value ? 16 : 10)), color: ks.map((k) => (k === sel.value ? COL.s2 : COL.s1)), line: { color: "#fff", width: 2 } },
        hovertemplate: "%{text}<br>days saved %{x:.1f}<br>late Δ %{y:.1f} pp<extra></extra>" }],
        { xaxis: { gridcolor: COL.grid, title: "promise days saved vs current (mean)" }, yaxis: { gridcolor: COL.grid, title: "late-rate change (pp)" }, margin: { l: 60, r: 16, t: 24, b: 44 },
          annotations: [{ xref: "paper", yref: "paper", x: 0, y: 1.08, showarrow: false, text: "Trade-off frontier: shorter promise vs more late orders", font: { size: 12, color: COL.text } }] });
    }
    renderSim();
    const h = P.padding.padding_histogram, hx = Object.keys(h).map(Number).sort((a, b) => a - b);
    plot("c-pad", [{ type: "bar", x: hx, y: hx.map((x) => h[Object.keys(h).find((k) => Number(k) === x)]), marker: { color: hx.map((x) => (x < 0 ? COL.s2 : COL.s1)) },
      hovertemplate: "%{x} days early: %{y:,} orders<extra></extra>" }],
      { xaxis: { gridcolor: COL.grid, title: "promised − actual days (negative = late)" }, yaxis: { gridcolor: COL.grid }, margin: { l: 52, r: 16, t: 24, b: 44 },
        annotations: [{ xref: "paper", yref: "paper", x: 0, y: 1.08, showarrow: false, text: `Median order arrives ${P.padding.overall_quantiles.p50} days before its promise; ${fmtPct(P.padding.share_padded_over_7_days, 0)} arrive >7 days early`, font: { size: 12, color: COL.text } }] });

    const DI = R.delivery_impact, dr = DI.review.F_dose_response;
    const series = [["fe", "FE controls", COL.s1], ["fe_plus_delivery_days", "+ same delivery time", COL.s2]];
    document.getElementById("t-c-dose").textContent = `Arriving early earns nothing; 4–14 days late costs ${Math.abs(dr.fe_plus_delivery_days[5].effect).toFixed(1)}–${Math.abs(dr.fe[6].effect).toFixed(1)} stars`;
    plot("c-dose", series.map(([k, n, c], j) => ({ type: "scatter", mode: "lines+markers", name: n, x: dr[k].map((r) => r.bin), y: dr[k].map((r) => r.effect),
      error_y: { type: "data", symmetric: false, array: dr[k].map((r) => r.ci95[1] - r.effect), arrayminus: dr[k].map((r) => r.effect - r.ci95[0]), color: c, thickness: 1.5, width: 3 },
      line: { color: c, width: 2 }, marker: { size: 8 }, hovertemplate: "%{x}: %{y:.2f} stars<extra>" + n + "</extra>" })),
      { showlegend: true, yaxis: { gridcolor: COL.grid, title: "Δ review score (stars)" }, xaxis: { gridcolor: COL.grid } });
    const bm = DI.rd.binned_means_minus10_to_plus10, bx = Object.keys(bm).map(Number).sort((a, b) => a - b);
    const rd5 = DI.rd.local_linear.find((r) => r.bandwidth_days === 5);
    document.getElementById("t-c-rd").textContent = `Breaking the promise by one day drops reviews ${Math.abs(rd5.estimate).toFixed(2)} stars at the cutoff (RD, ±5 d); the fall steepens after`;
    plot("c-rd", [{ type: "scatter", mode: "markers", x: bx, y: bx.map((x) => bm[x].mean), marker: { size: bx.map((x) => Math.max(6, Math.min(16, Math.sqrt(bm[x].n) / 4))), color: bx.map((x) => (x > 0 ? COL.s2 : COL.s1)), line: { color: "#fff", width: 1.5 } },
      customdata: bx.map((x) => bm[x].n), hovertemplate: "%{x} days vs promise: %{y:.2f} stars (n=%{customdata:,})<extra></extra>" }],
      { xaxis: { gridcolor: COL.grid, title: "delivered date − promised date (days)" }, yaxis: { gridcolor: COL.grid, title: "mean review score" },
        shapes: [{ type: "line", x0: 0.5, x1: 0.5, yref: "paper", y0: 0, y1: 1, line: { color: COL.muted, dash: "dot", width: 1 } }] });

    const L = R.lanes;
    document.getElementById("t-lanes").textContent = `SP→RJ alone has ${fmtN(L.worst_lanes[0].excess_late_orders)} excess late orders/yr (${fmtPct(L.worst_lanes[0].excess_late_orders / L.summary.excess_late_orders_total, 0)} of all excess)`;
    document.getElementById("lanes").innerHTML = `<table><tr><th>Lane</th><th class="n">Orders</th><th class="n">Late</th><th class="n">Excess late</th><th class="n">Seller-caused</th><th class="n">Med. days / promise</th><th class="n">1–2★ avoidable</th></tr>` +
      L.worst_lanes.slice(0, 10).map((r) => `<tr><td>${r.lane}</td><td class="n">${fmtN(r.delivered_orders)}</td><td class="n">${fmtPct(r.late_rate)}</td><td class="n">${fmtN(r.excess_late_orders)}</td><td class="n">${fmtPct(r.late_share_seller_handover_missed, 0)}</td><td class="n">${r.median_delivery_days.toFixed(1)} / ${r.median_promised_days}</td><td class="n">${fmtN(r.low_reviews_avoidable)}</td></tr>`).join("") +
      `</table><p class="cap" style="margin-top:6px">"Seller-caused" = share of the lane's late orders where the seller handed the parcel to the carrier after the shipping limit. The rest is carrier transit.</p>`;

    const A = R.anomalies, s = A.series, al = A.online_alerts;
    document.getElementById("t-c-anom").textContent = `Black Friday 2017 hit ${fmtN(A.black_friday_2017.orders)} orders (${A.black_friday_2017.multiple_of_expected_orders.toFixed(1)}× expected); ${A.n_online_investigate} of ${A.n_online_alerts} alerts needed a human`;
    plot("c-anom", [
      { type: "scatter", mode: "lines", x: s.map((r) => r.date), y: s.map((r) => r.orders), line: { color: COL.s1, width: 1.5 }, name: "orders", hovertemplate: "%{x}: %{y} orders<extra></extra>" },
      { type: "scatter", mode: "markers", x: al.map((r) => r.date), y: al.map((r) => r.orders), name: "alert",
        marker: { size: 10, symbol: al.map((r) => (r.classification === "expected_event" ? "diamond" : "x")), color: al.map((r) => (r.classification === "expected_event" ? COL.s3 : COL.bad)), line: { color: "#fff", width: 1.5 } },
        customdata: al.map((r) => [r.classification, r.known_event || "", r.orders_z.toFixed(1)]),
        hovertemplate: "%{x}<br>%{customdata[0]} %{customdata[1]}<br>z=%{customdata[2]}<extra></extra>" },
    ], { showlegend: true, yaxis: { gridcolor: COL.grid, title: "orders / day" },
         annotations: [{ x: "2017-11-24", y: A.black_friday_2017.orders, text: "Black Friday 2017 (expected event)", showarrow: true, arrowhead: 0, ax: -110, ay: 0, font: { size: 11 } },
                       { x: "2018-08-30", y: 0, text: "data feed ends (true positive)", showarrow: true, arrowhead: 0, ax: -20, ay: -150, font: { size: 11 } }] });
  }

  // ===== SELLERS & VOC
  document.getElementById("page-sellers").innerHTML =
    `<div class="grid g2">${card("c-pareto", "", "Cumulative GMV share by seller rank, Sep-2017…Aug-2018.")}
     <div class="card"><h2 id="t-tiers"></h2><p class="cap">Tier = scale (top-10% GMV) × quality bar (on-time ≥ network − 3 pp and review ≥ network − 0.2). Sellers with &lt;20 orders = long tail.</p><div id="tiers"></div></div></div>
     <div style="height:14px"></div>
     <div class="grid g2">${card("c-voc", "", "Transparent Portuguese keyword rules applied to every 1–2★ review with text (validated on 400 hand-labelled reviews; local qwen2.5:7b used as a cross-check on a subset).", "chart tall")}
     <div class="card"><h2 id="t-voclanes"></h2><p class="cap">1–2★ reviews with text by complaint reason, busiest lanes. The text says what the timestamps cannot: incomplete orders and wrong items.</p><div id="voclanes"></div></div></div>`;
  function renderSellers() {
    const S = R.sellers, P = S.pareto;
    document.getElementById("t-c-pareto").textContent = `Top 10% of sellers earn ${fmtPct(P.top_10pct_sellers_share, 0)} of GMV; 80% of GMV comes from ${fmtPct(P.share_of_sellers_for_80pct_gmv, 0)} of sellers (HHI ${S.hhi_window.toFixed(0)}: unconcentrated)`;
    plot("c-pareto", [{ type: "scatter", mode: "lines", x: P.curve.map((r) => r.seller_pct), y: P.curve.map((r) => r.gmv_cum_share), line: { color: COL.s1, width: 2 }, fill: "tozeroy", fillcolor: "rgba(42,120,214,0.08)",
      hovertemplate: "top %{x:.0%} of sellers → %{y:.0%} of GMV<extra></extra>" }],
      { xaxis: { gridcolor: COL.grid, tickformat: ".0%", title: "share of active sellers (ranked by GMV)" }, yaxis: { gridcolor: COL.grid, tickformat: ".0%", range: [0, 1.02] } });
    const t2 = S.tiers.find((t) => t.tier.startsWith("T2"));
    document.getElementById("t-tiers").textContent = `${t2.sellers} large sellers below the quality bar hold ${fmtPct(t2.gmv_share, 0)} of GMV: fix them first`;
    document.getElementById("tiers").innerHTML = `<table><tr><th>Tier</th><th class="n">Sellers</th><th class="n">GMV share</th><th class="n">On-time</th><th class="n">Review</th></tr>` +
      S.tiers.map((t) => `<tr><td>${t.tier}</td><td class="n">${fmtN(t.sellers)}</td><td class="n">${fmtPct(t.gmv_share)}</td><td class="n">${fmtPct(t.on_time)}</td><td class="n">${t.review.toFixed(2)}</td></tr>`).join("") +
      `</table><p class="cap" style="margin-top:8px">Fix-first sellers (top 5 by GMV):</p><table><tr><th>Seller</th><th>State</th><th class="n">GMV</th><th class="n">On-time</th><th class="n">Missed handover</th><th class="n">1–2★</th></tr>` +
      S.fix_first_sellers.slice(0, 5).map((r) => `<tr><td>${r.seller_id.slice(0, 8)}…</td><td>${r.seller_state}</td><td class="n">${fmtBRL(r.gmv_brl)}</td><td class="n">${fmtPct(r.on_time_rate)}</td><td class="n">${fmtPct(r.missed_handover_rate)}</td><td class="n">${fmtPct(r.low_review_share)}</td></tr>`).join("") + "</table>";
    const V = R.voc;
    if (!V || !V.negative_review_reason_share_weighted) { document.getElementById("c-voc").innerHTML = "<p class='muted'>VoC report not available.</p>"; return; }
    const a = V.negative_review_reason_share_weighted, b = V.negative_on_time_review_reason_share;
    const labs = Object.keys(a).sort((x, y) => a[x] - a[y]);
    const logi = (a.late_delivery || 0) + (a.not_received || 0);
    document.getElementById("t-c-voc").textContent = `${fmtPct(logi, 0)} of 1–2★ reviews are about delivery; on orders delivered ON TIME the #1 complaint is "${Object.keys(b).sort((x, y) => b[y] - b[x])[0].replace(/_/g, " ")}" (${fmtPct(b[Object.keys(b).sort((x, y) => b[y] - b[x])[0]], 0)})`;
    plot("c-voc", [
      { type: "bar", orientation: "h", name: "All 1–2★", y: labs, x: labs.map((l) => a[l]), marker: { color: COL.s1 }, hovertemplate: "%{y}: %{x:.1%}<extra>all 1–2★</extra>" },
      { type: "bar", orientation: "h", name: "1–2★ on orders delivered on time", y: labs, x: labs.map((l) => b[l] || 0), marker: { color: COL.s2 }, hovertemplate: "%{y}: %{x:.1%}<extra>on-time orders</extra>" },
    ], { barmode: "group", bargap: 0.25, showlegend: true, margin: { l: 140, r: 16, t: 8, b: 36 }, xaxis: { gridcolor: COL.grid, tickformat: ".0%" },
         annotations: [{ xref: "paper", yref: "paper", x: 1, y: 0.02, xanchor: "right", showarrow: false, text: `accuracy on fresh hand-labelled holdout (n=${V.evaluation.rules_gold_B_160_fresh_holdout.n}): ${fmtPct(V.evaluation.rules_gold_B_160_fresh_holdout.accuracy, 0)}, macro-F1 ${V.evaluation.rules_gold_B_160_fresh_holdout.macro_f1.toFixed(2)}`, font: { size: 11, color: COL.text2 } }] });
    const lanes = V.lanes_negative_reason_mix.slice(0, 8);
    const cols = ["late_delivery", "not_received", "incomplete_order", "damaged_defective", "wrong_item", "poor_quality"];
    const lx = V.sp_sp_vs_other_lanes_delivery_share;
    document.getElementById("t-voclanes").textContent = `Delivery complaints are ${fmtPct(lx.sp_sp, 0)} of 1–2★ text on SP→SP vs ${fmtPct(lx.other_lanes, 0)} on other lanes; ${fmtPct(V.incomplete_order_reviews_on_multi_item_orders, 0)} of "incomplete order" complaints are multi-item orders (${fmtPct(V.all_text_reviews_on_multi_item_orders, 0)} of reviews)`;
    document.getElementById("voclanes").innerHTML = `<table><tr><th>Lane</th><th class="n">1–2★ reviews</th>${cols.map((c) => `<th class="n">${c.replace(/_/g, " ")}</th>`).join("")}</tr>` +
      lanes.map((r) => `<tr><td>${r.lane}</td><td class="n">${fmtN(r.total)}</td>${cols.map((c) => `<td class="n">${fmtPct((r[c] || 0) / r.total, 0)}</td>`).join("")}</tr>`).join("") + "</table>";
  }

  // ===== ROOT CAUSE
  document.getElementById("page-rca").innerHTML =
    `<div class="card"><h2>Automated root cause: pick a KPI move</h2><p class="cap">Moves are found automatically (largest robust-z month-over-month changes). Each is split into mix (volume moved between segments) vs rate (segments themselves changed), per dimension, ranked by surprise (Jensen–Shannon divergence, as in Adtributor/ThirdEye).</p>
     <div class="sim-controls"><label>Move <select id="rca-move"></select></label></div><div id="rca-summary" class="callout"></div></div>
     <div style="height:14px"></div><div class="grid g3">${card("c-rca-0", "", "")}${card("c-rca-1", "", "")}${card("c-rca-2", "", "")}</div>
     <div style="height:14px"></div><div class="card"><h2>Simpson's-paradox scan</h2><div id="simpson"></div></div>`;
  function renderRCA() {
    const RC = R.root_cause, sel = document.getElementById("rca-move");
    if (!sel.options.length) {
      RC.moves.forEach((m, i) => { const o = document.createElement("option"); o.value = i; o.textContent = `${D.meta[m.kpi].label}: ${m.from_month.slice(0, 7)} → ${m.to_month.slice(0, 7)}`; sel.appendChild(o); });
      const def = RC.moves.findIndex((m) => m.kpi === "on_time_delivery_rate");
      sel.value = def >= 0 ? def : 0; sel.onchange = renderRCA;
    }
    const m = RC.moves[+sel.value], dims = m.dimension_ranking_by_surprise;
    const d0 = m.by_dimension[dims[0]], additive = d0.rate_effect == null;
    document.getElementById("rca-summary").innerHTML = additive
      ? `<b>${D.meta[m.kpi].label}</b> moved ${fmt(m.kpi, d0.kpi_from)} → ${fmt(m.kpi, d0.kpi_to)} (${fmtBRL(d0.delta)}). Additive KPI: each segment's bar is its own change. Most surprising dimension: <b>${dims[0]}</b>.`
      : `<b>${D.meta[m.kpi].label}</b> moved ${fmt(m.kpi, d0.kpi_from)} → ${fmt(m.kpi, d0.kpi_to)} (${fmtSigned(d0.delta, 3)}). By ${dims[0]}: rate effect <b>${fmtSigned(d0.rate_effect, 3)}</b>, mix effect <b>${fmtSigned(d0.mix_effect, 3)}</b>, interaction ${fmtSigned(d0.interaction, 3)}; ${fmtPct(d0.share_of_segments_improving, 0)} of volume sat in segments that improved.
         ${Math.abs(d0.rate_effect) > 5 * Math.abs(d0.mix_effect) ? "The move happened <b>inside</b> segments (network-wide), not because the order mix shifted." : "Mix shift matters here."} ${d0.simpson_paradox ? "<b>Simpson's paradox:</b> aggregate and within-segment move in opposite directions." : "No Simpson's paradox."}`;
    dims.forEach((dim, j) => {
      const d = m.by_dimension[dim], rows = d.top_segments.slice(0, 8).reverse();
      document.getElementById("t-c-rca-" + j).textContent = `${j === 0 ? "Most surprising: " : ""}${dim} — #1 ${rows[rows.length - 1].segment}`;
      document.getElementById("c-rca-" + j).previousElementSibling.textContent = `Top-3 segments explain ${fmtPct(d.top3_share_of_abs_movement, 0)} of |movement|; surprise ${d.surprise_js.toFixed(3)}.`;
      const traces = additive
        ? [{ type: "bar", orientation: "h", y: rows.map((r) => r.segment), x: rows.map((r) => r.contribution), marker: { color: rows.map((r) => (r.contribution >= 0 ? COL.s1 : COL.s2)) }, hovertemplate: "%{y}: %{x:,.0f}<extra></extra>" }]
        : [["rate", "rate", COL.s1], ["mix", "mix", COL.s2], ["interaction", "interaction", COL.neutral]].map(([k, n, c]) => ({
            type: "bar", orientation: "h", name: n, y: rows.map((r) => r.segment), x: rows.map((r) => r[k]), marker: { color: c }, hovertemplate: "%{y} " + n + ": %{x:.4f}<extra></extra>" }));
      plot("c-rca-" + j, traces, { barmode: "relative", showlegend: !additive && j === 0, margin: { l: 120, r: 12, t: 8, b: 30 }, xaxis: { gridcolor: COL.grid } });
    });
    const sc = RC.simpson_scan;
    document.getElementById("simpson").innerHTML = `Scanned ${sc.n_cases} KPI × month × dimension decompositions (on-time and review, every consecutive month pair). Simpson reversals: <b>${sc.n_simpson}</b>, of which material (hidden within-segment move ≥ 0.5 pp on-time / 0.02 stars): <b>${sc.n_material_simpson}</b>. All reversals occur when the aggregate barely moved (|Δ| ≤ ${sc.max_abs_delta_among_simpson_cases.toFixed(4)}), so headline KPI moves in this period can be read at face value.`;
  }

  // ---------- filter wiring
  const fFrom = document.getElementById("f-from"), fTo = document.getElementById("f-to"), fS = document.getElementById("f-state"), fC = document.getElementById("f-cat");
  C.months.forEach((m, i) => { fFrom.add(new Option(m, i)); fTo.add(new Option(m, i)); });
  fFrom.value = 0; fTo.value = C.months.length - 1;
  fS.add(new Option("All states", "ALL")); C.states.forEach((s) => fS.add(new Option(s, s)));
  fC.add(new Option("All categories", "ALL")); C.categories.forEach((c) => fC.add(new Option(c.replace(/_/g, " "), c)));
  function onFilter() {
    st.from = Math.min(+fFrom.value, +fTo.value); st.to = Math.max(+fFrom.value, +fTo.value);
    st.state = fS.value; st.cat = fC.value; renderExec();
  }
  [fFrom, fTo, fS, fC].forEach((el) => (el.onchange = onFilter));
  window.__setFilters = (o) => { if (o.state) fS.value = o.state; if (o.cat) fC.value = o.cat; if (o.from != null) fFrom.value = o.from; if (o.to != null) fTo.value = o.to; onFilter(); };

  const rendered = {};
  const renderers = { exec: () => { renderExecStatic(); renderExec(); }, growth: renderGrowth, customers: renderCustomers, delivery: renderDelivery, sellers: renderSellers, rca: renderRCA };
  function show() {
    const id = (location.hash || "#exec").slice(1);
    const pid = renderers[id] ? id : "exec";
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
