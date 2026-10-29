"""(H5) Voice of customer: complaint reasons from the real Portuguese review text.

Steps
  sample  : stratified random sample of reviews with text (by star rating), fixed seed.
  label   : zero-shot labelling with local Ollama qwen2.5:7b (temperature 0, JSON output).
            Labels are cached in artifacts/voc_llm_labels.csv (review_key -> label) so
            `make all` does not need the LLM; `make voc-relabel` re-runs it.
  report  : accuracy / macro-F1 vs the hand-checked gold sample (artifacts/voc_gold_labels.csv),
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


def cmd_report() -> None:
    keys = pd.read_csv(SAMPLE_FILE)
    pop = population()
    lab = pd.read_csv(LLM_FILE)
    s = pop.merge(keys, on=["review_key", "stratum"]).merge(lab, on="review_key")
    s = s[~s.llm_label.str.startswith("error")]
    n_pop = pop.groupby("stratum").size()
    n_s = s.groupby("stratum").size()
    s["weight"] = s.stratum.map(n_pop / n_s)

    gold = pd.read_csv(GOLD_FILE)
    g = s.merge(gold, on="review_key")
    acc = float((g.gold_label == g.llm_label).mean())
    f1, per = macro_f1(g.gold_label, g.llm_label)
    # Bootstrap CI for accuracy on the gold sample
    rng = np.random.default_rng(1)
    hits = (g.gold_label == g.llm_label).to_numpy()
    boots = [hits[rng.integers(0, len(hits), len(hits))].mean() for _ in range(2000)]
    confusion = pd.crosstab(g.gold_label, g.llm_label)

    neg = s[s.review_score <= 2]
    w_share = (neg.groupby("llm_label")["weight"].sum() / neg["weight"].sum()).sort_values(
        ascending=False
    )
    # External validity: does the text say "late/not received" when the data says late?
    delivered = s[s.is_delivered.fillna(False)]
    late_txt = delivered.llm_label.isin(["late_delivery", "not_received"])
    ext = {
        "late_or_not_received_label_rate_when_order_late": float(
            late_txt[delivered.is_late.fillna(False)].mean()
        ),
        "late_or_not_received_label_rate_when_on_time": float(
            late_txt[~delivered.is_late.fillna(False)].mean()
        ),
        "not_received_label_rate_when_order_undelivered": float(
            (s.loc[~s.is_delivered.fillna(False), "llm_label"] == "not_received").mean()
        ),
        "n_undelivered_in_sample": int((~s.is_delivered.fillna(False)).sum()),
    }
    # Reasons tied to sellers and lanes (1-2 star reviews, weighted counts)
    by_seller = neg.assign(w=neg.weight).pivot_table(
        index="primary_seller_id", columns="llm_label", values="w", aggfunc="sum", fill_value=0
    )
    by_seller["total"] = by_seller.sum(axis=1)
    top_sellers = by_seller.sort_values("total", ascending=False).head(10)
    top_sellers["top_reason"] = top_sellers.drop(columns="total").idxmax(axis=1)
    by_lane = neg.pivot_table(
        index="lane", columns="llm_label", values="weight", aggfunc="sum", fill_value=0
    )
    by_lane["total"] = by_lane.sum(axis=1)
    lane_tbl = by_lane[by_lane.total >= 100].copy()
    for c in ["late_delivery", "not_received", "incomplete_order", "damaged_defective"]:
        if c in lane_tbl:
            lane_tbl[f"{c}_share"] = lane_tbl[c] / lane_tbl["total"]
    lane_tbl = lane_tbl.sort_values("total", ascending=False).head(12)
    # Reasons on ON-TIME negative reviews: what goes wrong when logistics did not.
    ontime_neg = neg[neg.is_delivered.fillna(False) & ~neg.is_late.fillna(False)]
    ontime_share = (
        ontime_neg.groupby("llm_label")["weight"].sum() / ontime_neg["weight"].sum()
    ).sort_values(ascending=False)
    write_report(
        "voc",
        {
            "model": MODEL,
            "taxonomy": LABELS,
            "sample_design": {
                "strata": STRATA,
                "seed": SEED,
                "population_by_stratum": n_pop,
                "labelled": int(len(s)),
                "label_errors": int(len(lab) - len(s)),
            },
            "gold": {
                "n": int(len(g)),
                "labeller": "hand-labelled blind (model labels hidden) by the project author "
                "spot-check recommended",
                "accuracy": acc,
                "accuracy_ci95": [
                    float(np.quantile(boots, 0.025)),
                    float(np.quantile(boots, 0.975)),
                ],
                "macro_f1": f1,
                "per_class": per,
                "confusion": confusion.reset_index().to_dict(orient="records"),
                "majority_class_baseline_accuracy": float(
                    g.gold_label.value_counts(normalize=True).iloc[0]
                ),
            },
            "external_validity": ext,
            "negative_review_reason_share_weighted": w_share,
            "negative_on_time_review_reason_share": ontime_share,
            "sellers_most_negative_reviews": top_sellers.reset_index(),
            "lanes_negative_reason_mix": lane_tbl.reset_index(),
        },
    )
    print(f"gold n={len(g)} acc={acc:.3f} macroF1={f1:.3f}")
    print(w_share.round(3).to_string())
    print(ext)


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or ["report"])[0]
    {
        "sample": cmd_sample,
        "label": cmd_label,
        "gold-export": cmd_gold_export,
        "report": cmd_report,
    }[cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
