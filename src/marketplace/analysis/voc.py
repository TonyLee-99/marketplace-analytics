"""(H5) Voice of customer: complaint reasons from the real Portuguese review text.

Steps
  sample  : stratified random sample of reviews with text (by star rating), fixed seed.
  label   : zero-shot labelling with local Ollama qwen2.5:7b (temperature 0, JSON output).
            Labels are cached in artifacts/voc_llm_labels.csv (review_key -> label) so
            `make all` does not need the LLM; `make voc-relabel` re-runs it.
  report  : agreement / macro-F1 vs the labelled sets (artifacts/voc_gold_*.csv),
            an external sanity check (late_delivery/not_received labels vs the order's real
            delivery status), population-weighted reason shares, and reasons by seller / lane.

Run: python -m marketplace.analysis.voc {sample|label|gold-export|report}
"""

from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from marketplace.analysis.common import WINDOW_END, WINDOW_START, df, write_report
from marketplace.analysis.voc_prompt import LABELS, SYSTEM, user_prompt
from marketplace.paths import ROOT

ART = ROOT / "artifacts"
SAMPLE_FILE = ART / "voc_sample_keys.csv"
LLM_FILE = ART / "voc_llm_labels.csv"
GOLD_FILE = ART / "voc_gold_labels.csv"
STRATA = {"1": 1200, "2": 600, "3": 600, "4-5": 600}
GOLD_PER_STRATUM = 60
SEED = 20261029
OLLAMA = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:7b"


def population() -> pd.DataFrame:
    p = df(
        f"""
        select review_key, order_id, review_score, review_title, review_message,
               primary_seller_id, lane, primary_category, customer_state, is_delivered,
               is_late, days_late, purchase_month
        from marts.fct_reviews
        where review_message is not null
          and purchase_month between '{WINDOW_START}' and '{WINDOW_END}'
        """
    )
    p["stratum"] = np.where(p.review_score >= 4, "4-5", p.review_score.astype(str))
    return p


def cmd_sample() -> None:
    p = population()
    parts = [p[p.stratum == s].sample(n=n, random_state=SEED) for s, n in STRATA.items()]
    s = pd.concat(parts)
    rng = np.random.default_rng(SEED)
    s["in_gold"] = False
    for st in STRATA:
        idx = s.index[s.stratum == st]
        s.loc[rng.choice(idx, GOLD_PER_STRATUM, replace=False), "in_gold"] = True
    ART.mkdir(exist_ok=True)
    s[["review_key", "stratum", "in_gold"]].to_csv(SAMPLE_FILE, index=False)
    print(f"sampled {len(s)} reviews; gold subset {int(s.in_gold.sum())}")


def _ask(row) -> tuple[str, str]:
    body = json.dumps(
        {
            "model": MODEL,
            "stream": False,
            "format": "json",
            "keep_alive": "60m",
            "options": {"temperature": 0, "num_predict": 24, "seed": 7},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt(row.review_title, row.review_message)},
            ],
        }
    ).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    try:
        out = json.load(urllib.request.urlopen(req, timeout=120))["message"]["content"]
        label = json.loads(out).get("label", "other")
    except Exception as e:  # noqa: BLE001 - record and continue
        return row.review_key, f"error:{type(e).__name__}"
    return row.review_key, label if label in LABELS else "other"


def cmd_label(workers: int = 1) -> None:
    keys = pd.read_csv(SAMPLE_FILE)
    p = population().merge(keys, on=["review_key", "stratum"])
    done = (
        pd.read_csv(LLM_FILE)
        if LLM_FILE.exists()
        else pd.DataFrame(columns=["review_key", "llm_label"])
    )
    todo = p[~p.review_key.isin(done.review_key)]
    print(f"{len(todo)} to label ({len(done)} cached)")
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(_ask, todo.itertuples()), 1):
            results.append(r)
            if i % 100 == 0 or i == len(todo):
                new = pd.DataFrame(results, columns=["review_key", "llm_label"])
                pd.concat([done, new]).to_csv(LLM_FILE, index=False)
                print(f"  {i}/{len(todo)}", flush=True)


def cmd_gold_export() -> None:
    """Print the gold subset texts (WITHOUT model labels) for blind hand-labelling."""
    keys = pd.read_csv(SAMPLE_FILE)
    p = population().merge(keys[keys.in_gold], on=["review_key", "stratum"])
    for r in p.sort_values("review_key").itertuples():
        title = f"[{r.review_title}] " if r.review_title else ""
        print(
            f"{r.review_key}\t{r.review_score}\t{title}{r.review_message}".replace(
                "\r", " "
            ).replace("\n", " ")
        )


HOLDOUT_FILE = ART / "voc_gold_holdout_keys.csv"
HOLDOUT_PER_STRATUM = 40


def _print_rows(p: pd.DataFrame) -> None:
    for r in p.sort_values("review_key").itertuples():
        title = f"[{r.review_title}] " if r.review_title else ""
        text = f"{r.review_key}\t{r.review_score}\t{title}{r.review_message}"
        print(text.replace("\r", " ").replace("\n", " "))


def cmd_holdout_export() -> None:
    """Fresh gold set B: reviews NOT in the labelling sample, drawn before any rules existed."""
    keys = pd.read_csv(SAMPLE_FILE)
    pop = population()
    rest = pop[~pop.review_key.isin(keys.review_key)]
    parts = [
        rest[rest.stratum == s].sample(n=HOLDOUT_PER_STRATUM, random_state=SEED + 1) for s in STRATA
    ]
    h = pd.concat(parts)
    if not HOLDOUT_FILE.exists():
        h[["review_key", "stratum"]].to_csv(HOLDOUT_FILE, index=False)
    _print_rows(h)


def cmd_dev_export() -> None:
    """Development sample for writing keyword rules: sample rows that are NOT in any gold set."""
    keys = pd.read_csv(SAMPLE_FILE)
    p = population().merge(keys[~keys.in_gold], on=["review_key", "stratum"])
    p = p[p.review_score <= 3]
    _print_rows(p.sample(n=300, random_state=SEED + 2))


def macro_f1(y: pd.Series, p: pd.Series) -> tuple[float, dict]:
    per = {}
    for c in sorted(set(y) | set(p)):
        tp = ((y == c) & (p == c)).sum()
        fp = ((y != c) & (p == c)).sum()
        fn = ((y == c) & (p != c)).sum()
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[c] = {"precision": prec, "recall": rec, "f1": f1, "support": int((y == c).sum())}
    present = [c for c in per if per[c]["support"] > 0]
    return float(np.mean([per[c]["f1"] for c in present])), per


def _score(gold: pd.DataFrame, pred_col: str) -> dict:
    g = gold.dropna(subset=[pred_col])
    if g.empty:
        return {"n": 0}
    hits = (g.gold_label == g[pred_col]).to_numpy()
    rng = np.random.default_rng(1)
    boots = [hits[rng.integers(0, len(hits), len(hits))].mean() for _ in range(2000)]
    f1, per = macro_f1(g.gold_label, g[pred_col])
    return {
        "n": int(len(g)),
        "accuracy": float(hits.mean()),
        "accuracy_ci95": [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))],
        "macro_f1": f1,
        "per_class": per,
        "majority_class_baseline_accuracy": float(
            g.gold_label.value_counts(normalize=True).iloc[0]
        ),
        "confusion": pd.crosstab(g.gold_label, g[pred_col]).reset_index().to_dict(orient="records"),
    }


def corrected_shares(gold: pd.DataFrame, pred: pd.Series, n_boot: int = 500) -> dict:
    """Misclassification-corrected class shares: observed predicted shares q = M^T p, where
    M[i, j] = P(pred=j | silver=i) is estimated on the silver set; solve for p >= 0 (NNLS),
    renormalise, bootstrap the silver rows for a 95% CI."""
    from scipy.optimize import nnls

    labels = sorted(set(LABELS))
    q = pred.value_counts(normalize=True).reindex(labels, fill_value=0).to_numpy()

    def solve(g):
        m = pd.crosstab(g.gold_label, g.rule_label).reindex(index=labels, columns=labels, fill_value=0)
        rows = m.sum(axis=1).replace(0, np.nan)
        mm = (m.T / rows).T.fillna(0)
        for i in range(len(labels)):  # unseen true class: assume perfect classification
            if rows.isna().iloc[i]:
                mm.iloc[i, i] = 1.0
        p, _ = nnls(mm.to_numpy().T, q)
        return p / p.sum() if p.sum() else p

    point = solve(gold)
    rng = np.random.default_rng(3)
    boots = np.array([solve(gold.iloc[rng.integers(0, len(gold), len(gold))]) for _ in range(n_boot)])
    return {lab: {"observed": float(q[i]), "corrected": float(point[i]),
                  "ci95": [float(np.quantile(boots[:, i], 0.025)), float(np.quantile(boots[:, i], 0.975))]}
            for i, lab in enumerate(labels)}


def cmd_rescore(path: str) -> None:
    """Score rules and silver labels against a blind second-pass labelling once the template is filled."""
    from marketplace.analysis.voc_rules import classify

    t = pd.read_csv(path)
    t = t[t["author_label"].notna() & (t["author_label"].astype(str).str.strip() != "")]
    t["rule_label"] = [classify(None, m, int(sc)) for m, sc in zip(t.review_text_pt, t.stars, strict=True)]
    silver = pd.concat([pd.read_csv(GOLD_FILE), pd.read_csv(ART / "voc_gold_holdout_labels.csv")])
    t = t.merge(silver, on="review_key", how="left")
    print(f"n={len(t)}  rules vs author: {(t.rule_label == t.author_label).mean():.3f}  "
          f"silver vs author: {(t.gold_label == t.author_label).mean():.3f}")


def cmd_report() -> None:
    from marketplace.analysis.voc_rules import classify

    pop = population()
    pop["rule_label"] = [
        classify(t, m, int(sc))
        for t, m, sc in zip(pop.review_title, pop.review_message, pop.review_score, strict=True)
    ]
    lab = (
        pd.read_csv(LLM_FILE)
        if LLM_FILE.exists()
        else pd.DataFrame(columns=["review_key", "llm_label"])
    )
    lab = lab[~lab.llm_label.astype(str).str.startswith("error")]
    pop = pop.merge(lab, on="review_key", how="left")

    gold_a = pd.read_csv(GOLD_FILE).merge(pop, on="review_key")
    gold_b = pd.read_csv(ART / "voc_gold_holdout_labels.csv").merge(pop, on="review_key")
    gold_ab = pd.concat([gold_a, gold_b])
    evaluation = {
        "rules_vs_silver_A_240_seen_before_rules": _score(gold_a, "rule_label"),
        "rules_vs_silver_B_160_fresh_holdout": _score(gold_b, "rule_label"),
        "rules_vs_silver_A_plus_B": _score(gold_ab, "rule_label"),
    }
    both = pop.dropna(subset=["llm_label"])
    agreement = {
        "n_reviews_with_both_labels": int(len(both)),
        "rule_llm_agreement": float((both.rule_label == both.llm_label).mean())
        if len(both)
        else None,
    }

    neg = pop[pop.review_score <= 2]
    share = neg.rule_label.value_counts(normalize=True)
    delivered = pop[pop.is_delivered.fillna(False)]
    late_txt = delivered.rule_label.isin(["late_delivery", "not_received"])
    is_late = delivered.is_late.fillna(False).astype(bool)
    ext = {
        "late_or_not_received_label_rate_when_order_late": float(late_txt[is_late].mean()),
        "late_or_not_received_label_rate_when_on_time": float(late_txt[~is_late].mean()),
        "not_received_label_rate_when_order_undelivered": float(
            (
                pop.loc[~pop.is_delivered.fillna(False).astype(bool), "rule_label"]
                == "not_received"
            ).mean()
        ),
        "n_undelivered_with_text": int((~pop.is_delivered.fillna(False).astype(bool)).sum()),
    }
    ontime_neg = neg[
        neg.is_delivered.fillna(False).astype(bool) & ~neg.is_late.fillna(False).astype(bool)
    ]
    ontime_share = ontime_neg.rule_label.value_counts(normalize=True)
    # Reasons tied to sellers and lanes (counts of 1-2 star reviews with text).
    by_seller = neg.pivot_table(
        index="primary_seller_id",
        columns="rule_label",
        values="review_key",
        aggfunc="count",
        fill_value=0,
    )
    by_seller["total"] = by_seller.sum(axis=1)
    top_sellers = by_seller.sort_values("total", ascending=False).head(10).copy()
    top_sellers["top_reason"] = top_sellers.drop(columns="total").idxmax(axis=1)
    by_lane = neg.pivot_table(
        index="lane", columns="rule_label", values="review_key", aggfunc="count", fill_value=0
    )
    by_lane["total"] = by_lane.sum(axis=1)
    lane_tbl = by_lane[by_lane.total >= 100].sort_values("total", ascending=False).head(12)
    sp_sp = by_lane.loc["SP>SP"] if "SP>SP" in by_lane.index else None
    far = by_lane[~by_lane.index.str.startswith("SP>SP") & (by_lane.total >= 50)].sum()
    incomplete_multi = df(
        """
        select r.order_id, o.n_items, o.n_sellers
        from marts.fct_reviews r join marts.fct_orders o using (order_id)
        where r.review_message is not null
        """
    )
    pop2 = pop.merge(incomplete_multi, on="order_id", how="left")
    inc = pop2[pop2.rule_label == "incomplete_order"]
    write_report(
        "voc",
        {
            "primary_labeller": "keyword rules (src/marketplace/analysis/voc_rules.py) on ALL reviews with text",
            "secondary_labeller": f"{MODEL} zero-shot via Ollama on part of a stratified sample "
            "(stopped: the shared laptop ran out of memory and requests took 75-120 s)",
            "taxonomy": LABELS,
            "population": {
                "reviews_with_text": int(len(pop)),
                "negative_1_2_star_with_text": int(len(neg)),
                "by_stratum": pop.stratum.value_counts(),
            },
            "silver_labels": {
                **evaluation["rules_vs_silver_A_plus_B"],
                "status": "Single-annotator labels. Set A (240) was "
                "read before the rules were written; set B (160) was drawn and labelled before any rule "
                "existed; rules were developed on a disjoint dev sample. No inter-annotator agreement measured yet.",
                "verification": "artifacts/voc_author_verification_template.csv (50 reviews) -> "
                "`python -m marketplace.analysis.voc rescore <filled.csv>`",
            },
            "evaluation": evaluation,
            "rule_vs_llm": agreement,
            "external_validity": ext,
            "negative_review_reason_share_weighted": share,
            "negative_share_corrected_for_misclassification": corrected_shares(
                gold_ab[gold_ab.review_score <= 2], neg.rule_label),
            "negative_on_time_share_corrected_for_misclassification": corrected_shares(
                gold_ab[gold_ab.review_score <= 2], ontime_neg.rule_label),
            "accuracy_by_star_stratum_silver_B": {
                str(k): float((g.gold_label == g.rule_label).mean())
                for k, g in gold_b.groupby("stratum")},
            "negative_on_time_review_reason_share": ontime_share,
            "incomplete_order_reviews_on_multi_item_orders": float((inc.n_items > 1).mean()),
        "incomplete_order_1_2_star_reviews": int((inc.review_score <= 2).sum()),
        "incomplete_order_1_2_star_gmv_brl": float(
            pop2[(pop2.rule_label == "incomplete_order") & (pop2.review_score <= 2)]
            .merge(df("select order_id, items_price_brl::double gmv from marts.fct_orders"),
                   on="order_id")["gmv"].sum()),
        "months_covered": int(pop.purchase_month.nunique()),
            "incomplete_order_reviews_on_multi_seller_orders": float((inc.n_sellers > 1).mean()),
        "all_text_reviews_on_multi_item_orders": float((pop2.n_items > 1).mean()),
        "all_text_reviews_on_multi_seller_orders": float((pop2.n_sellers > 1).mean()),
            "sellers_most_negative_reviews": top_sellers.reset_index(),
            "lanes_negative_reason_mix": lane_tbl.reset_index(),
            "sp_sp_vs_other_lanes_delivery_share": {
                "sp_sp": float(
                    (sp_sp.get("late_delivery", 0) + sp_sp.get("not_received", 0)) / sp_sp["total"]
                )
                if sp_sp is not None
                else None,
                "other_lanes": float(
                    (far.get("late_delivery", 0) + far.get("not_received", 0)) / far["total"]
                ),
            },
            "review_keys_with_labels_file": "artifacts/voc_rule_labels.csv",
        },
    )
    pop[["review_key", "rule_label"]].to_csv(ART / "voc_rule_labels.csv", index=False)
    e = evaluation
    print(
        f"rules vs silver A {e['rules_vs_silver_A_240_seen_before_rules']['accuracy']:.3f}, "
        f"silver B {e['rules_vs_silver_B_160_fresh_holdout']['accuracy']:.3f} "
        f"(macro-F1 {e['rules_vs_silver_B_160_fresh_holdout']['macro_f1']:.3f})"
    )
    print(share.round(3).to_string())
    print(ext, agreement)


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or ["report"])[0]
    {
        "sample": cmd_sample,
        "label": cmd_label,
        "gold-export": cmd_gold_export,
        "holdout-export": cmd_holdout_export,
        "dev-export": cmd_dev_export,
        "report": cmd_report,
        "rescore": lambda: cmd_rescore(sys.argv[2]),
    }[cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
